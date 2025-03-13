FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y make aria2 jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set up a new user named "user" with user ID 1000
RUN useradd -m -u 1000 user

# Switch to the "user" user
USER user

# Set home to the user's home directory
ENV HOME=/home/user \
	PATH=/home/user/.local/bin:$PATH

# Copy the scripts and Makefile into the container
COPY --chown=user scripts/ $HOME/scripts/
COPY --chown=user Makefile $HOME/

# Set the working directory to the user's home directory
WORKDIR $HOME

CMD ["make", "export"]
