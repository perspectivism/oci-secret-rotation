# Multi-stage build based on the Oracle Functions Python template: dependencies
# are installed into /python in the build stage and copied into the final image,
# keeping pip cache and build artifacts out of the runtime layer.
FROM fnproject/python:3.12 AS build-stage
WORKDIR /function
COPY requirements.txt /function/
RUN pip3 install --target /python/ --no-cache-dir -r requirements.txt

FROM fnproject/python:3.12
WORKDIR /function
COPY --from=build-stage /python /python
COPY . /function/
ENV PYTHONPATH=/python:/function
ENTRYPOINT ["/python/bin/fdk", "/function/func.py", "handler"]
