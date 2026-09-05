from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scholarmind.db.models import IngestionJob, Paper
from scholarmind.domain.arxiv import parse_arxiv_identifier
from scholarmind.domain.errors import ConflictError, NotFoundError
from scholarmind.domain.papers import JobStage, JobStatus, PaperStatus, ensure_paper_transition
from scholarmind.repositories.papers import PaperRepository


@dataclass(frozen=True, slots=True)
class PaperCreation:
    paper: Paper
    job: IngestionJob
    created: bool


class PaperService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = PaperRepository(session)

    async def create(
        self,
        owner_id: str,
        raw_identifier: str,
        max_attempts: int = 3,
    ) -> PaperCreation:
        identifier = parse_arxiv_identifier(raw_identifier)
        existing = await self.repository.get_by_arxiv(identifier.canonical, owner_id)
        if existing is not None:
            if existing.history_hidden:
                existing.history_hidden = False
                await self.session.commit()
                await self.session.refresh(existing, ["updated_at"])
            latest = _latest_loaded_job(existing)
            if latest is None:
                latest = IngestionJob(paper_id=existing.id, max_attempts=max_attempts)
                self.session.add(latest)
                await self.session.commit()
                await self.session.refresh(latest)
            return PaperCreation(existing, latest, False)

        paper_id = uuid4()
        paper = Paper(
            id=paper_id,
            owner_id=owner_id,
            arxiv_id=identifier.canonical,
            base_arxiv_id=identifier.base_id,
            arxiv_version=identifier.version,
            abstract_url=identifier.abstract_url,
            pdf_url=identifier.pdf_url,
            status=PaperStatus.QUEUED,
            retrieval_namespace=f"paper-{paper_id.hex}",
        )
        job = IngestionJob(
            paper=paper,
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            max_attempts=max_attempts,
        )
        self.repository.add(paper)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            concurrent = await self.repository.get_by_arxiv(identifier.canonical, owner_id)
            if concurrent is None:
                raise
            latest = _latest_loaded_job(concurrent)
            if latest is None:
                raise
            return PaperCreation(concurrent, latest, False)
        await self.session.refresh(paper)
        await self.session.refresh(job)
        return PaperCreation(paper, job, True)

    async def get(self, paper_id: UUID, owner_id: str) -> Paper:
        paper = await self.repository.get(paper_id, owner_id)
        if paper is None:
            raise NotFoundError("paper", str(paper_id))
        return paper

    async def remove_from_history(self, paper_id: UUID, owner_id: str) -> None:
        paper = await self.get(paper_id, owner_id)
        paper.history_hidden = True
        await self.session.commit()

    async def retry(
        self,
        paper_id: UUID,
        owner_id: str,
        max_attempts: int = 3,
    ) -> PaperCreation:
        paper = await self.repository.get(paper_id, owner_id, lock=True)
        if paper is None:
            raise NotFoundError("paper", str(paper_id))
        if paper.status == PaperStatus.QUEUED:
            latest = _latest_loaded_job(paper)
            if latest is not None and latest.status == JobStatus.QUEUED:
                # A previous enqueue can fail after the database commit. Reuse the same
                # deterministic job so a subsequent request repairs the handoff safely.
                return PaperCreation(paper, latest, False)
        if paper.status != PaperStatus.FAILED:
            raise ConflictError(
                "paper_not_retryable",
                "Only failed or not-yet-enqueued papers can be retried",
                status=paper.status.value,
            )
        ensure_paper_transition(paper.status, PaperStatus.QUEUED)
        paper.status = PaperStatus.QUEUED
        paper.error_code = None
        paper.error_message = None
        job = IngestionJob(
            paper=paper,
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            max_attempts=max_attempts,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return PaperCreation(paper, job, True)


def _latest_loaded_job(paper: Paper) -> IngestionJob | None:
    return max(paper.jobs, key=lambda item: item.created_at) if paper.jobs else None
