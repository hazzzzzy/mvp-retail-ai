from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.engine import engine
from app.db.models import Base

TEXT_TYPES = {"char", "varchar", "text", "tinytext", "mediumtext", "longtext", "enum", "set"}


def _quote_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


async def sync_comments() -> None:
    async with engine.begin() as conn:
        db = await conn.scalar(text("SELECT DATABASE()"))
        print(f"db={db}")

        for table in Base.metadata.sorted_tables:
            table_name = table.name
            await conn.execute(
                text(f"ALTER TABLE `{table_name}` COMMENT = :comment"),
                {"comment": table.comment or ""},
            )

            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA,
                               CHARACTER_SET_NAME, COLLATION_NAME, DATA_TYPE
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tb
                        ORDER BY ORDINAL_POSITION
                        """
                    ),
                    {"db": db, "tb": table_name},
                )
            ).mappings().all()
            by_name = {r["COLUMN_NAME"]: r for r in rows}

            for col in table.columns:
                meta = by_name.get(col.name)
                if meta is None:
                    continue

                parts: list[str] = [meta["COLUMN_TYPE"]]
                data_type = (meta["DATA_TYPE"] or "").lower()
                if data_type in TEXT_TYPES:
                    if meta["CHARACTER_SET_NAME"]:
                        parts.append(f"CHARACTER SET {meta['CHARACTER_SET_NAME']}")
                    if meta["COLLATION_NAME"]:
                        parts.append(f"COLLATE {meta['COLLATION_NAME']}")

                parts.append("NULL" if meta["IS_NULLABLE"] == "YES" else "NOT NULL")

                default = meta["COLUMN_DEFAULT"]
                if default is not None:
                    ds = str(default)
                    if ds.upper() in {"CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()", "NOW()"}:
                        parts.append("DEFAULT CURRENT_TIMESTAMP")
                    else:
                        try:
                            float(ds)
                            parts.append(f"DEFAULT {ds}")
                        except ValueError:
                            parts.append(f"DEFAULT {_quote_str(ds)}")

                extra = (meta["EXTRA"] or "").strip()
                if extra:
                    # MySQL 8 的 DEFAULT_GENERATED 不可直接放入 MODIFY COLUMN。
                    extra = " ".join([x for x in extra.split() if x.upper() != "DEFAULT_GENERATED"])
                    if extra:
                        parts.append(extra)

                sql = f"ALTER TABLE `{table_name}` MODIFY COLUMN `{col.name}` {' '.join(parts)} COMMENT :comment"
                await conn.execute(text(sql), {"comment": col.comment or ""})

            print(f"synced: {table_name}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(sync_comments())
