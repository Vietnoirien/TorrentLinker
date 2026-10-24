"""Owner APIs share the application's cookie and CSRF protection."""

from torrentlinker.assistant.models import Conversation, Message, Schedule
from torrentlinker.assistant.providers import Provider
from torrentlinker.assistant.research import SearchSettings


def routes(app, assistant):
    @app.get("/api/setup/assistant")
    def setup():
        return assistant.setup()

    @app.post("/api/setup/assistant/providers")
    def create(body: Provider):
        return assistant.save_provider(body)

    @app.put("/api/setup/assistant/providers/{identifier}")
    def edit(identifier: str, body: Provider):
        return assistant.save_provider(body, identifier)

    @app.post("/api/setup/assistant/providers/{identifier}/test")
    def test(identifier: str):
        return assistant.test_provider(identifier)

    @app.get("/api/setup/assistant/providers/{identifier}/models")
    def models(identifier: str):
        return assistant.models.models(
            assistant.provider(identifier), assistant.secrets.get("assistant:" + identifier)
        )

    @app.post("/api/assistant/conversations")
    def conversation(body: Conversation):
        return assistant.create_conversation(body)

    @app.get("/api/assistant/conversations")
    def conversations():
        return assistant.conversations()

    @app.post("/api/assistant/jobs", status_code=202)
    def start(body: Message):
        return assistant.start(body.conversation_id, body.message)

    @app.get("/api/assistant/jobs")
    def history(conversation_id: str = ""):
        return assistant.history(conversation_id)

    @app.get("/api/assistant/jobs/{identifier}")
    def run(identifier: str):
        return assistant.run(identifier)

    @app.post("/api/assistant/jobs/{identifier}/cancel")
    def cancel(identifier: str):
        return assistant.cancel(identifier)

    @app.post("/api/assistant/schedules/preview")
    def preview(body: Schedule):
        import time

        return {"next_at": body.next_at(time.time()), "policy": body.policy.model_dump()}

    @app.get("/api/assistant/schedules")
    def schedules():
        return assistant.schedules()

    @app.post("/api/assistant/schedules")
    def schedule(body: Schedule):
        return assistant.save_schedule(body)

    @app.put("/api/assistant/schedules/{identifier}")
    def edit_schedule(identifier: str, body: Schedule):
        return assistant.save_schedule(body, identifier)

    @app.post("/api/assistant/schedules/{identifier}/run", status_code=202)
    def run_schedule(identifier: str):
        return assistant.run_schedule(identifier)

    @app.get("/api/setup/assistant/research")
    def research_settings():
        return assistant.research_settings()

    @app.put("/api/setup/assistant/research")
    def research(body: SearchSettings):
        return assistant.save_research(body)

    @app.post("/api/setup/assistant/models")
    def discover_models(body: Provider):
        return assistant.models.models(body, body.api_key or "")
