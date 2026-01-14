---
id: getting-started
title: Getting Started
sidebar_position: 2
---

# Getting Started

Ready to start training your Voice AI? This guide will help you get EfficientAI running on your computer in just a few minutes.

## Prerequisites

Before we begin, make sure you have these installed on your computer:
*   **Docker**: This helps run the application in a self-contained box, so you don't have to install a bunch of complex software manually.

## Quick Start

The easiest way to run EfficientAI is using Docker. It handles setting up the database, the website, and the backend logic for you.

1.  **Open your Terminal** (Command Prompt).
2.  **Navigate** to the folder where you downloaded EfficientAI.
3.  **Run this command**:

    ```bash
    docker compose up -d
    ```

    *   *What this does*: It downloads all the necessary parts and starts them up in the background. It might take a few minutes the first time.

4.  **Create an API Key**:
    You need a key to log in and use the system. Run this command to generate one:

    ```bash
    docker compose exec api python scripts/create_api_key.py "My First Key"
    ```

    *   *Copy the key* it prints out! You will need it.

5.  **Launch the App**:
    Open your web browser (like Chrome) and go to:
    
    [http://localhost:8000/](http://localhost:8000/)

    You should see the EfficientAI dashboard!

## Next Steps

Now that you are running, let's set up your first test:

1.  **Connect your Agent**: Go to the "Agents" tab and tell us how to connect to your Voice AI.
2.  **Create a Persona**: Go to "Personas" and create a test caller (e.g., "Standard American Caller").
3.  **Run a Test**: Go to "Evaluators" and launch a test call!
