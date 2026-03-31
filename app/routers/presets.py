from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel

from app.models.train import Preset, PresetCreate
from app.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

settings = get_settings()

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])


def get_db():
    """Get database connection for presets."""
    engine = create_engine(f"sqlite:///{settings.sqlite_db_path}")
    return engine


class PresetDB:
    """Database operations for presets."""

    def __init__(self):
        self.engine = create_engine(f"sqlite:///{settings.sqlite_db_path}")
        self.Session = sessionmaker(bind=self.engine)
        self._init_table()

    def _init_table(self):
        """Initialize presets table."""
        with self.engine.connect() as conn:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    origin_stop_id TEXT NOT NULL,
                    destination_stop_id TEXT,
                    direction TEXT NOT NULL,
                    preferred_types TEXT
                )
            """)
            )
            conn.commit()

    def get_all(self) -> list[Preset]:
        """Get all presets."""
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM presets ORDER BY name"))
            rows = result.fetchall()

        presets = []
        for row in rows:
            preferred_types = []
            if row.preferred_types:
                preferred_types = row.preferred_types.split(",")

            presets.append(
                Preset(
                    id=row.id,
                    name=row.name,
                    origin_stop_id=row.origin_stop_id,
                    destination_stop_id=row.destination_stop_id,
                    direction=row.direction,
                    preferred_types=preferred_types,
                )
            )
        return presets

    def get_by_id(self, preset_id: int) -> Optional[Preset]:
        """Get preset by ID."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM presets WHERE id = :id"),
                {"id": preset_id},
            )
            row = result.fetchone()

        if not row:
            return None

        preferred_types = []
        if row.preferred_types:
            preferred_types = row.preferred_types.split(",")

        return Preset(
            id=row.id,
            name=row.name,
            origin_stop_id=row.origin_stop_id,
            destination_stop_id=row.destination_stop_id,
            direction=row.direction,
            preferred_types=preferred_types,
        )

    def create(self, preset: PresetCreate) -> Preset:
        """Create a new preset."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                INSERT INTO presets (name, origin_stop_id, destination_stop_id, direction, preferred_types)
                VALUES (:name, :origin_stop_id, :destination_stop_id, :direction, :preferred_types)
            """),
                {
                    "name": preset.name,
                    "origin_stop_id": preset.origin_stop_id,
                    "destination_stop_id": preset.destination_stop_id,
                    "direction": preset.direction,
                    "preferred_types": ",".join(preset.preferred_types) if preset.preferred_types else None,
                },
            )
            conn.commit()
            preset_id = result.lastrowid

        return Preset(
            id=preset_id,
            name=preset.name,
            origin_stop_id=preset.origin_stop_id,
            destination_stop_id=preset.destination_stop_id,
            direction=preset.direction,
            preferred_types=preset.preferred_types,
        )

    def delete(self, preset_id: int) -> bool:
        """Delete a preset."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM presets WHERE id = :id"),
                {"id": preset_id},
            )
            conn.commit()
            return result.rowcount > 0


preset_db = PresetDB()


@router.get("", response_model=list[Preset])
async def get_presets():
    """Get all saved presets."""
    return preset_db.get_all()


@router.get("/{preset_id}", response_model=Preset)
async def get_preset(preset_id: int):
    """Get a specific preset."""
    preset = preset_db.get_by_id(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.post("", response_model=Preset)
async def create_preset(preset: PresetCreate):
    """Create a new preset."""
    return preset_db.create(preset)


@router.delete("/{preset_id}")
async def delete_preset(preset_id: int):
    """Delete a preset."""
    if not preset_db.delete(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"status": "deleted"}
