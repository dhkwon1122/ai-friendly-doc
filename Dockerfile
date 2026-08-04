FROM python:3.11-slim

WORKDIR /app

# 사내 PyPI 저장소를 써야 하면 빌드 시 --build-arg PIP_INDEX_URL=... 로 넘기면 된다.
# 지정하지 않으면 기존과 동일하게 공개 PyPI를 사용한다.
# 사내 저장소가 자체 서명 인증서를 쓰면 PIP_TRUSTED_HOST도 같이 넘기면 된다
# (예: --build-arg PIP_TRUSTED_HOST=nexus.internal.example.com).
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0 \
    PORT=12345

EXPOSE 12345

CMD ["ai-friendly-doc-web"]
