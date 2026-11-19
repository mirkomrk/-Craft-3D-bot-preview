# Craft3D AI

Telegram bot for receiving, archiving and generating 3D model previews using SolidCraft CLI.

## Features

- Telegram bot with administrator access controls.
- 3D model upload and preview generation.
- STL, 3MF, STEP and STP support.
- GLB and GLTF support.
- SolidCraft CLI rendering engine.
- Docker Compose deployment.
- Separate storage for original models, previews and projects.

## Requirements

- Linux host.
- Docker Engine and Docker Compose plugin.
- Telegram bot token from [@BotFather](https://t.me/BotFather).
- Telegram API credentials from [my.telegram.org](https://my.telegram.org).

## Configuration

Create the environment file:

    cp .env.example .env
    chmod 600 .env

Edit `.env` and configure the required Telegram credentials and application settings.

## Build

Build the Docker images:

    docker compose build

Start the application only after configuring a dedicated Telegram bot token:

    docker compose up -d

## Rendering

3D previews are generated using SolidCraft CLI.

Blender is not required by the rendering pipeline.

Original uploaded models are retained separately from generated previews.
