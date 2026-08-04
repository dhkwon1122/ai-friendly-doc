FROM python:3.11-slim

WORKDIR /app

# 사내 PyPI 저장소를 써야 하면 빌드 시 --build-arg PIP_INDEX_URL=... 로 넘기면 된다.
# 지정하지 않으면 기존과 동일하게 공개 PyPI를 사용한다.
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0 \
    PORT=12345

EXPOSE 12345

CMD ["ai-friendly-doc-web"]
