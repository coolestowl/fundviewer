FROM python:3.12-slim
WORKDIR /app
# ADD requirements.txt /app
RUN pip install -i https://mirrors.bfsu.edu.cn/pypi/web/simple bs4 pandas httpx async-cache pydantic-settings fastapi uvicorn[standand] jinja2 python-multipart lxml
ADD . /app
CMD ["python", "main.py"]