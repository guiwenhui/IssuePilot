from typing import Awaitable, Callable, Tuple
from uuid import UUID

from app.checkpoints.postgres import PostgresCheckpointFactory
from app.core.config import Settings
from app.db.session import session_factory
from app.llms.ollama import OllamaChatProvider
from app.services.git_client import GitClient
from app.services.implementation_service import ImplementationService
from app.services.implementation_store import SqlImplementationStore
from app.services.implementation_workspace import ImplementationWorkspace
from app.services.patch_service import PatchLimits, PatchService
from app.services.test_runner import DockerTestRunner
from app.services.workspace import WorkspaceManager
from app.workers.implementation_queue import ImplementationQueue


def build_implementation_runtime(
    settings: Settings,
    git_client: GitClient,
    workspace: WorkspaceManager,
    provider: OllamaChatProvider,
    checkpoint_factory: PostgresCheckpointFactory,
) -> Tuple[
    ImplementationWorkspace,
    PatchService,
    DockerTestRunner,
    ImplementationQueue,
]:
    implementation_workspace = ImplementationWorkspace(
        workspace.root, git_client
    )
    patch_service = PatchService(
        git_client,
        PatchLimits(
            settings.implementation_max_files,
            settings.implementation_max_file_bytes,
            settings.implementation_max_total_bytes,
            settings.implementation_max_diff_bytes,
            settings.implementation_max_changed_lines,
        ),
    )
    test_runner = DockerTestRunner(
        settings.test_runner_image,
        settings.test_timeout_seconds,
        settings.test_max_output_bytes,
    )
    queue = ImplementationQueue(
        settings.implementation_queue_capacity,
        _implementation_handler(
            settings,
            git_client,
            workspace,
            implementation_workspace,
            patch_service,
            provider,
            checkpoint_factory,
            test_runner,
        ),
        settings.implementation_enabled,
    )
    return implementation_workspace, patch_service, test_runner, queue


def _implementation_handler(
    settings: Settings,
    git_client: GitClient,
    workspace: WorkspaceManager,
    implementation_workspace: ImplementationWorkspace,
    patch_service: PatchService,
    provider: OllamaChatProvider,
    checkpoint_factory: PostgresCheckpointFactory,
    test_runner: DockerTestRunner,
) -> Callable[[str, UUID], Awaitable[None]]:
    async def process_work(kind: str, item_id: UUID) -> None:
        async with session_factory() as session:
            service = ImplementationService(
                SqlImplementationStore(session),
                git_client,
                workspace,
                implementation_workspace,
                patch_service,
                provider,
                checkpoint_factory,
                test_runner,
                settings.implementation_enabled,
            )
            if kind == "implementation":
                await service.process_implementation(item_id)
            else:
                await service.process_test(item_id)

    return process_work
