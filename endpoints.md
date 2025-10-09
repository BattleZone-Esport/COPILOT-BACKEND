# API Endpoints

This document outlines the API endpoints for the application, how to use them, and what they are for.

## Authentication (`/v1/auth`)

These endpoints handle user authentication. The primary method is via Google OAuth.

### **GET `/v1/auth/login`**

- **Description:** This endpoint is not an API endpoint in the traditional sense but rather a page that can be rendered to the user to start the login process. It shows a login button.
- **Frontend Usage:** You can link a user to this page, or more directly, to the `/v1/auth/google/login` endpoint.

### **GET `/v1/auth/google/login`**

- **Description:** Initiates the Google OAuth2 login flow. It redirects the user to Google's authentication page.
- **Frontend Usage:** This is the main endpoint to use for starting the login process. Create a button or link that points to this URL.
  ```html
  <a href="/v1/auth/google/login">Login with Google</a>
  ```

### **GET `/v1/auth/google/callback`**

- **Description:** This is the callback URL that Google redirects to after successful authentication. It's handled automatically by the backend. It creates a user session, sets a `csrf_token` in the session, and redirects the user to the root (`/`).
- **Frontend Usage:** No direct interaction is needed from the frontend. After this, the user should be authenticated, and subsequent API requests will be associated with their session.

### **GET `/v1/auth/logout`**

- **Description:** Logs the user out by clearing their session.
- **Frontend Usage:** Link a "Logout" button to this endpoint.
  ```html
  <a href="/v1/auth/logout">Logout</a>
  ```

## Jobs (`/v1/jobs`)

These endpoints are for creating and managing jobs. All endpoints here require the user to be authenticated.

### **POST `/v1/jobs`**

- **Description:** Creates a new job. This is the primary endpoint for interacting with the AI agents.
- **Frontend Usage:** This is used to start a new task, such as code generation, debugging, or having a conversation with a chatbot. You need to send a POST request with a JSON body.

- **Body:**
  ```json
  {
    "prompt": "The user's request, e.g., 'fix this code for me' or 'hello, who are you?'",
    "options": {
      "mode": "sync",
      "pipeline_name": "ureshii-p1",
      "coder_model": "qwen/qwen3-coder:free",
      "debugger_model": "deepseek/deepseek-chat-v3.1:free",
      "fixer_model": "nvidia/nemotron-nano-9b-v2:free",
      "chatbot_model": "qwen/qwen3-30b-a3b:free",
      "github_repo": "user/repo",
      "github_branch": "main",
      "github_file_path": "src/index.js"
    }
  }
  ```

- **Options Breakdown:**
    - `mode`: `"sync"` or `"queue"`. `"sync"` will block until the job is complete, while `"queue"` will return immediately with a job ID for polling.
    - `pipeline_name`: Specifies which pipeline to use.
        - `"ureshii-p1"`: The default pipeline for coding, debugging, and fixing tasks. It uses the `coder`, `debugger`, and `fixer` agents.
        - `"chat"`: The pipeline for conversational interactions. It uses the `chatbot` agent.
    - `coder_model`: (Optional) The model to use for the Coder agent. Defaults to the system's default coder model.
    - `debugger_model`: (Optional) The model to use for the Debugger agent. Defaults to the system's default debugger model.
    - `fixer_model`: (Optional) The model to use for the Fixer agent. Defaults to the system's default fixer model.
    - `chatbot_model`: (Optional) The model to use for the Chatbot agent when `pipeline_name` is `"chat"`. Defaults to the system's default chatbot model.
    - `github_repo`, `github_branch`, `github_file_path`: (Optional) GitHub-related context for the job.

- **Example: Starting a Chatbot Conversation**
  ```json
  {
    "prompt": "Hello! Can you tell me a joke?",
    "options": {
      "pipeline_name": "chat",
      "chatbot_model": "qwen/qwen3-30b-a3b:free"
    }
  }
  ```

- **Example: Fixing a file in GitHub**
   ```json
  {
    "prompt": "This file has a bug. Please fix it.",
    "options": {
      "pipeline_name": "ureshii-p1",
      "fixer_model": "nvidia/nemotron-nano-9b-v2:free",
      "github_repo": "your-username/your-repo",
      "github_branch": "bug-fix-branch",
      "github_file_path": "path/to/buggy/file.py"
    }
  }
  ```

- **CSRF Protection:** This endpoint requires a CSRF token. You must include a `X-CSRF-Token` header in your request. The `csrf_token` is available in the user's session after login. You might need an endpoint to expose this token to your frontend SPA or embed it in the page's meta tags if you are using server-side rendering.

### **GET `/v1/jobs`**

- **Description:** Lists all the jobs created by the currently authenticated user. Supports pagination.
- **Frontend Usage:** To display a user's job history.
- **Query Parameters:**
  - `skip` (optional, default: 0): Number of jobs to skip.
  - `limit` (optional, default: 10): Maximum number of jobs to return.
- **Example:** `fetch('/v1/jobs?limit=20')`

### **GET `/v1/jobs/{job_id}`**

- **Description:** Retrieves the details of a single job by its ID.
- **Frontend Usage:** To view the status and details of a specific job.
- **Example:** `fetch('/v1/jobs/some-job-uuid')`

### **GET `/v1/jobs/{job_id}/result`**

- **Description:** Gets the final result of a completed job. This includes any generated content or artifacts.
- **Frontend Usage:** Once a job's status is 'completed', you can use this endpoint to fetch the output and display it to the user.
- **Example:** `fetch('/v1/jobs/some-job-uuid/result')`

## Webhooks (`/v1/webhooks`)

These endpoints are for receiving data from external services.

### **POST `/v1/webhooks/qstash`**

- **Description:** This is an internal webhook used by the QStash service for processing asynchronous jobs.
- **Frontend Usage:** This endpoint is not intended for direct use by the frontend. It's part of the backend's asynchronous task processing infrastructure.
