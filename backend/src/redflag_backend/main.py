import os

from redflag_backend.app import create_app
from redflag_backend.settings import Settings

# Hosts such as Render expose the deployed commit as RENDER_GIT_COMMIT.
app = create_app(Settings(commit_sha=os.environ.get("RENDER_GIT_COMMIT")))
