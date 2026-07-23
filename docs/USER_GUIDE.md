# Apervia User Guide

This guide follows the real signed-in interface and explains the basic path for configuring a model, starting a conversation, managing files and knowledge bases, connecting MCP, and using sandbox tools.

## 1. Explore the workspace

![Apervia signed-in workspace](images/workspace-desktop.png)

The page has five main areas:

1. **Model selector**: The current model appears at the top. If no model is selected, configure an API key and model first.
2. **Sidebar shortcuts**: Start a new conversation, search, retrieve generated images, or open the library.
3. **Conversation list**: Stores regular conversations. Temporary chats are not retained like normal conversation history.
4. **Input area**: Enter a request, use **+** to add files and options, and use the controls on the right for voice input or sending.
5. **Account menu**: Select the avatar in the lower-left corner to open the profile, personalization, settings, or sign-out actions.

### Project release announcements

![Apervia 1.0.0 project release announcement](images/release-announcement-desktop.png)

After an upgrade, the workspace displays the formal release notes for the new version. Selecting **Got it** stores an acknowledgement for the current account, so the same account will not see that release again on another device. Closing the announcement hides it only for the current page session.

## 2. Configure a model for the first time

Open the account menu in the lower-left corner and select **Settings**:

![Apervia API settings](images/settings-desktop.png)

### 2.1 Save an API key

1. Open **API settings**.
2. Select **Chat Completions** or **Responses**.
3. Enter a recognizable name for the key.
4. Enter the API key and API base URL.
5. Select **Save key**.

Chat Completions and Responses are different protocols. Even when they use the same provider, configure each according to its actual API. Do not copy Responses fields into Chat requests or vice versa.

### 2.2 Add and select a model

1. Open **Model management** in Settings.
2. Add or synchronize available models for the saved key.
3. Confirm that each model is assigned to the correct API type.
4. Close Settings and select a model from the model name at the top of the workspace.

If the model list is empty, check the key, base URL, API type, and whether the provider implements a model-list endpoint.

## 3. Start and manage conversations

- Select **New conversation** to create an independent session.
- Enter a request and send it. Verify important conclusions independently.
- Use **Search** in the sidebar to find conversation history.
- Rename or delete conversations from the sidebar.
- Use **Temporary chat** at the top when the conversation should not enter normal history.

Keep one topic in each conversation when possible. Start a new conversation when the task changes substantially to reduce context mixing.

## 4. Files and library

### Conversation attachments

Select **+** on the left side of the input box to upload files needed for the current task. Files and generated results belong to the current account.

### Library

Open **Library** from the sidebar to manage documents that should remain available over time. It is suitable for policies, manuals, project materials, and knowledge documents that need to be retrieved across conversations.

Guidelines:

- Use conversation attachments for temporary analysis.
- Put reusable, searchable content in the library.
- After updating a document, check its parsing status to avoid using an outdated index.
- Do not upload personal data or confidential files that you are not authorized to process.

## 5. Web search and SearXNG

Configure the search service under **Settings → Web settings**. When Apervia runs in Docker and SearXNG runs on the host, use an address such as:

```text
http://host.docker.internal:18080
```

Keep the search path as `/search`. Do not use the container's own `localhost`. See the [Integration Guide](INTEGRATIONS.md) for details.

## 6. MCP tools

Add a trusted server under **Settings → MCP**:

1. Enter the MCP server name and URL.
2. Select OAuth or a compatible bearer-token method.
3. Complete server-side authorization and scan for tools.
4. Enable the required tools and select a permission level.
5. Keep per-call confirmation enabled for high-risk operations.

Enter passwords only on the MCP server's authorization page. If `mcp_server_private_network_blocked` appears, check Clash/Mihomo Fake-IP DNS configuration instead of disabling private-address protection. See the [Integration Guide](INTEGRATIONS.md).

## 7. Sandbox and code/file tools

An administrator must enable the Sandbox Runner in the deployment environment. Only then do Chat and Responses receive `sandbox_*` tool definitions.

The sandbox is suitable for:

- Running controlled Python, Node.js, and similar tasks.
- Reading and generating files for the current task.
- Processing Office, PDF, image, and OCR content.
- Verifying code in a temporary directory.

Regular execution containers have networking disabled and a read-only root filesystem. They can see only the temporary volume for the current task and cannot read the App's `/data`. Use an explicit network-enabled tool when a task requires network access; do not attempt to bypass sandbox boundaries.

## 8. Personalization, data, and account

Use the account menu and Settings to manage:

- Profile and personalization preferences.
- Conversation and data settings.
- Storage assigned to the current account.
- Account security and deletion.

Export any data that must be retained before deletion. Contact the instance administrator when an account is pending approval, disabled, or in a deletion period.

## 9. Troubleshooting

### No model is selected

Save a key, add a model under **Model management**, and then select it at the top of the workspace.

### A host API cannot be reached

Do not use `127.0.0.1` from inside a container to reach a host service. Use `host.docker.internal` and verify the service bind address and firewall.

### Sandbox tools do not appear

Confirm that the administrator set `SANDBOX_TOOLS_ENABLED=1`, that the App and Runner share the same `SANDBOX_RUNNER_SECRET`, and that the Runner is healthy.

### A new account cannot sign in

Accounts registered after the first one require administrator approval at `/admin` by default. See the [Administrator Guide](ADMIN_GUIDE.md).
