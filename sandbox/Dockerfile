FROM python:3.11-slim

# 安全加固
RUN useradd -m -s /bin/bash sandbox && \
    mkdir -p /code && \
    chown sandbox:sandbox /code

# 白名单库（只读安装）
RUN pip install --no-cache-dir \
    requests==2.31.0 \
    beautifulsoup4==4.12.3 \
    pandas==2.1.4 \
    numpy==1.26.4 \
    lxml==5.0.0

# 只装标准库之外的有限依赖

COPY runner.py /code/runner.py
RUN chmod 444 /code/runner.py

USER sandbox
WORKDIR /code

ENTRYPOINT ["python", "/code/runner.py"]
