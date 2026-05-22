from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def landing():
    return {"status": "ok"}
