# Multi-stage build: install dependencies into /python in the build stage,
# then copy only the installed packages into the final image. This keeps the
# final image lean and avoids build-time tools in the runtime layer.
FROM fnproject/python:3.12 AS build-stage
WORKDIR /function
ADD requirements.txt /function/
RUN pip3 install --target /python/ --no-cache --no-cache-dir -r requirements.txt

FROM fnproject/python:3.12
WORKDIR /function
COPY --from=build-stage /python /python
ADD . /function/
ENV PYTHONPATH=/python
ENTRYPOINT ["/python/bin/fdk", "/function/func.py", "handler"]
