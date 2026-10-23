"""Incremental market updates. IDs and personal references are never replaced."""
import re
import unicodedata


def normalized_name(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


class MarketSync:
    """Use inside one caller-owned transaction; ambiguous matches abort it."""
    def __init__(self, connection):
        self.connection = connection
        self.company_index = {}
        self.offer_index = {}
        self.created = {"companies": 0, "offers": 0}
        self.updated = {"companies": 0, "offers": 0}
        for table, index, keys in (("companies", self.company_index, self.company_keys), ("offers", self.offer_index, self.offer_keys)):
            cursor = connection.execute("SELECT * FROM " + table)
            columns = [col[0] for col in cursor.description]
            for values in cursor.fetchall():
                row = dict(zip(columns, values))
                for key in keys(row):
                    index.setdefault(key, set()).add(row["id"])

    @staticmethod
    def company_keys(row):
        name = normalized_name(row.get("name"))
        return [("name", name)] if name else []

    @staticmethod
    def offer_keys(row):
        keys = []
        url = str(row.get("url") or "").strip().rstrip("/")
        if url:
            keys.append(("url", url))
        title = normalized_name(row.get("title"))
        company = normalized_name(row.get("company_name")) or str(row.get("company_id") or "")
        if title and company:
            keys.append(("posting", str(row.get("source") or "").strip().casefold(), company, title,
                         str(row.get("location") or "").strip().casefold(), str(row.get("offer_type") or "").strip().casefold(),
                         str(row.get("publication_date") or "").strip()))
        return keys

    def _upsert(self, table, values, index, keys):
        candidates = set()
        for key in keys:
            candidates.update(index.get(key, set()))
        if len(candidates) > 1:
            raise ValueError("Ambiguous %s identity; no rows were merged. Review duplicates before importing." % table)
        if candidates:
            row_id = next(iter(candidates))
            if table == "offers" and values.get("company_id") is not None:
                previous = self.connection.execute("SELECT company_id FROM offers WHERE id=?", (row_id,)).fetchone()[0]
                if previous is not None and previous != values["company_id"]:
                    raise ValueError("An existing offer cannot silently move to another company")
            # Empty incoming fields cannot erase existing metadata or skills.
            fields = {k: v for k, v in values.items() if v not in (None, "") and k != "has_offer"}
            if fields:
                self.connection.execute("UPDATE " + table + " SET " + ", ".join(k + "=?" for k in fields) + " WHERE id=?", (*fields.values(), row_id))
            self.updated[table] += 1
        else:
            schema = {col[1]: col for col in self.connection.execute("PRAGMA table_info(" + table + ")")}
            values = dict(values)
            for column, value in values.items():
                if value is None and schema[column][3]:
                    values[column] = 0 if any(term in schema[column][2].upper() for term in ("INT", "REAL", "FLOAT", "NUM")) else ""
            columns = list(values)
            cursor = self.connection.execute("INSERT INTO " + table + " (" + ", ".join(columns) + ") VALUES (" + ", ".join("?" for _ in columns) + ")", tuple(values.values()))
            row_id = cursor.lastrowid
            self.created[table] += 1
        for key in keys:
            index.setdefault(key, set()).add(row_id)
        return row_id

    def company(self, values):
        if not self.company_keys(values):
            raise ValueError("Company name is required")
        return self._upsert("companies", values, self.company_index, self.company_keys(values))

    def offer(self, values):
        if not str(values.get("title") or "").strip() or not self.offer_keys(values):
            raise ValueError("Offer title and identity are required")
        return self._upsert("offers", values, self.offer_index, self.offer_keys(values))
