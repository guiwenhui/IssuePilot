FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

RUN pip install --no-cache-dir pytest==8.4.2

COPY --chmod=0555 run_pytest.py /opt/issuepilot/run_pytest.py

USER 65534:65534
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/issuepilot/run_pytest.py"]
