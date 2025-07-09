import uvicorn
import os
import shutil
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException
from starlette.background import BackgroundTask
from process_data import process_data

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/process_data")
def parse_file_endpoint(
        flag: int = Form(...),
        true_position: str = Form(...),
        event: str = Form(...),
        pos_threshold: int = Form(...),
        duration: int = Form(...),
        good_pos_counter: int = Form(...),
        file: UploadFile = File(...),
        user_true_lat: float = Form(...),
        user_true_lon: float = Form(...),
        ) -> JSONResponse:

    if user_true_lat != 0 and user_true_lon != 0:
        true_lat, true_lon = user_true_lat, user_true_lon
    else:
        true_lat, true_lon = [float(i) for i in true_position.split(',')]

    try:
        contents = file.file.read()
        with open(file.filename, 'w+b') as f:
            f.write(contents)
            f.flush()
            result = process_data(
                flag=flag,
                true_lat=true_lat,
                true_lon=true_lon,
                event=event,
                pos_threshold=pos_threshold,
                duration=duration,
                good_pos_counter=good_pos_counter,
                file=f.name,
            )

            if result is None:
                raise HTTPException(status_code=400, detail='''Statistics is empty, check parameters!
                                                    Usually True position is incorrect or others.''')

            return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            content={
                "error": str(e)
            }, status_code=500,
        )
    finally:
        file.file.close()

@app.get('/api/download_results')
def download_and_cleanup(file: str,
                         is_checked: bool
                         ) -> FileResponse:

    result_file = os.path.splitext(file)[0] + '_results.txt'
    result_file_path = os.path.join(os.getcwd(),'results',result_file)
    result_folder = os.path.join(os.getcwd(),'results')
    return FileResponse(path=result_file_path,
                        filename=result_file,
                        media_type='multipart/form-data',
                        background=BackgroundTask(cleanup, result_folder, is_checked, file))


@app.get('/api/clear_all_results', status_code=200)
def clear_all_results() -> JSONResponse:
    result_folder = os.path.join(os.getcwd(),'results')
    cleanup(
        result_folder=result_folder,
        is_checked=True
    )
    content = {
        'Deletion': 'OK'
    }
    return JSONResponse(content=content)


@app.get('/api/health', status_code=200)
def return_status_ok() -> JSONResponse:
    content = {
        "status": "ok"
    }
    return JSONResponse(content=content)


def cleanup(result_folder: str,
            is_checked: bool,
            file: str = ''
            ) -> None:

    if is_checked:
        for filename in os.listdir():
            if filename.endswith(".log") and file in filename:
                os.remove(filename)
        for filename in os.listdir(result_folder):
            file_path = os.path.join(result_folder, filename)
            try:
                if (os.path.isfile(file_path) or os.path.islink(file_path)) and os.path.splitext(file)[0] in file_path:
                    os.unlink(file_path)
                elif os.path.isdir(file_path) and os.path.splitext(file)[0] in file_path:
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Error when removing {file_path}: {e}')


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
