from __future__ import annotations

from app.core.db import Database

# Таблицы, которые не показываем LLM (внутренние/служебные).
_INTERNAL_TABLES = {"chat_messages"}


async def load_schema(db: Database) -> dict[str, dict]:
    """Читает структуру схемы БД из каталога (information_schema).

    Возвращает: { table: {"columns": [ {"name","type","is_pk","is_fk"} ... ] } }
    По таблицам public, кроме служебных. Без хардкода структуры — берём из БД.
    """
    col_rows = await db.fetch_readonly(
        "SELECT c.table_name, c.column_name, c.data_type "
        "FROM information_schema.columns c "
        "JOIN information_schema.tables t "
        "ON c.table_schema = t.table_schema AND c.table_name = t.table_name "
        "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
        "ORDER BY c.table_name, c.ordinal_position"
    )
    pk_rows = await db.fetch_readonly(
        "SELECT tc.table_name, kcu.column_name "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
        "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY'"
    )
    fk_rows = await db.fetch_readonly(
        "SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table, "
        "ccu.column_name AS ref_column "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
        "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'FOREIGN KEY'"
    )

    pk = {(r["table_name"], r["column_name"]) for r in pk_rows}
    fk = {(r["table_name"], r["column_name"]) for r in fk_rows}
    fk_targets = {(r["table_name"], r["column_name"]): (r["ref_table"], r["ref_column"])
                  for r in fk_rows}

    schema: dict[str, dict] = {}
    for r in col_rows:
        table = r["table_name"]
        if table in _INTERNAL_TABLES:
            continue
        col = {
            "name": r["column_name"],
            "type": r["data_type"],
            "is_pk": (table, r["column_name"]) in pk,
            "is_fk": (table, r["column_name"]) in fk,
        }
        target = fk_targets.get((table, r["column_name"]))
        if target:
            col["fk_target"] = f"{target[0]}.{target[1]}"
        schema.setdefault(table, {"columns": []})["columns"].append(col)
    return schema
