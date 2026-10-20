FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    sudo bash build-essential git curl wget pkg-config \
    ca-certificates software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Accept host UID/GID as build args so files are owned by the host user
ARG USERNAME=developer
ARG UID=1000
ARG GID=1000

# Create group and user once, set up passwordless sudo
RUN groupadd --gid ${GID} ${USERNAME} && \
    useradd \
      --uid ${UID} \
      --gid ${GID} \
      --create-home \
      --shell /bin/bash \
      ${USERNAME} && \
    usermod -aG sudo ${USERNAME} && \
    mkdir -p /etc/sudoers.d && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} && \
    chmod 0440 /etc/sudoers.d/${USERNAME}

# Switch to the user BEFORE installing uv and Python
# so everything lands in the correct home directory
USER ${USERNAME}

# Install uv into the user's home
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/home/${USERNAME}/.local/bin:${PATH}"

# Install Python 3.11 and pin it as the uv default
RUN uv python install 3.11
ENV UV_PYTHON=3.11

WORKDIR /app


COPY requirements.txt .
RUN uv venv --python 3.11
ENV VIRTUAL_ENV=/home/${USERNAME}/.venv
RUN uv venv $VIRTUAL_ENV --python 3.11
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN uv pip install -r requirements.txt

CMD ["/bin/bash"]

