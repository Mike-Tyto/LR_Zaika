import logging
from typing import List, Dict, Optional

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("api_client")


class IdentificationRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    title: Optional[str] = Field(default=None, alias="Title")
    category: Optional[str] = Field(default=None, alias="Category")
    attack_type: Optional[str] = Field(default=None, alias="Attack Type")


class AttackDescriptionRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    scenario_description: Optional[str] = Field(default=None, alias="Scenario Description")
    attack_steps: Optional[str] = Field(default=None, alias="Attack Steps")
    tools_used: Optional[str] = Field(default=None, alias="Tools Used")


class TargetVulnerabilityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    target_type: Optional[str] = Field(default=None, alias="Target Type")
    vulnerability: Optional[str] = Field(default=None, alias="Vulnerability")
    mitre_technique: Optional[str] = Field(default=None, alias="MITRE Technique")


class ImpactProtectionRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    impact: Optional[str] = Field(default=None, alias="Impact")
    detection_method: Optional[str] = Field(default=None, alias="Detection Method")
    solution: Optional[str] = Field(default=None, alias="Solution")


class MetadataRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    tags: Optional[str] = Field(default=None, alias="Tags")
    source: Optional[str] = Field(default=None, alias="Source")


class APIClient:
    def __init__(self, base_url: str, login: str, password: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            auth=(login, password),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        self._client.close()

    def _get_json(self, path: str) -> List[Dict]:
        try:
            resp = self._client.get(path)
        except httpx.TimeoutException:
            log.error("Таймаут при запросе %s", path)
            raise RuntimeError(f"Таймаут при запросе {path}")
        except httpx.RequestError as e:
            log.error("Ошибка соединения при запросе %s: %s", path, e)
            raise RuntimeError(f"Ошибка соединения: {e}")

        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized — неверный логин/пароль")
        if resp.status_code == 403:
            raise RuntimeError("403 Forbidden — доступ запрещён")
        if resp.status_code == 404:
            raise RuntimeError(f"404 Not Found — эндпоинт {path} не существует")
        if 500 <= resp.status_code < 600:
            raise RuntimeError(f"{resp.status_code} Server Error на {path}")
        if resp.status_code != 200:
            raise RuntimeError(f"Неожиданный статус {resp.status_code} на {path}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Ответ {path} не является JSON")

        if not isinstance(data, list):
            if isinstance(data, dict) and "items" in data:
                data = data["items"]
            else:
                raise RuntimeError(f"Ожидался список JSON на {path}, получено {type(data)}")

        log.info("GET %s -> %s, строк: %d", path, resp.status_code, len(data))
        return data

    def fetch_identification(self) -> List[IdentificationRow]:
        raw = self._get_json("/api/identification")
        return [IdentificationRow.model_validate(row) for row in raw]

    def fetch_attack_description(self) -> List[AttackDescriptionRow]:
        raw = self._get_json("/api/attack_description")
        return [AttackDescriptionRow.model_validate(row) for row in raw]

    def fetch_target_vulnerability(self) -> List[TargetVulnerabilityRow]:
        raw = self._get_json("/api/target_vulnerability")
        return [TargetVulnerabilityRow.model_validate(row) for row in raw]

    def fetch_impact_protection(self) -> List[ImpactProtectionRow]:
        raw = self._get_json("/api/impact_protection")
        return [ImpactProtectionRow.model_validate(row) for row in raw]

    def fetch_metadata(self) -> List[MetadataRow]:
        raw = self._get_json("/api/metadata")
        return [MetadataRow.model_validate(row) for row in raw]

    def fetch_all(self) -> pd.DataFrame:
        """Загружает все 5 групп и объединяет их в один DataFrame по id."""
        dfs = {
            "identification": pd.DataFrame([m.model_dump() for m in self.fetch_identification()]),
            "attack_description": pd.DataFrame([m.model_dump() for m in self.fetch_attack_description()]),
            "target_vulnerability": pd.DataFrame([m.model_dump() for m in self.fetch_target_vulnerability()]),
            "impact_protection": pd.DataFrame([m.model_dump() for m in self.fetch_impact_protection()]),
            "metadata": pd.DataFrame([m.model_dump() for m in self.fetch_metadata()]),
        }

        for name, df in dfs.items():
            log.info("Группа %-20s строк: %d", name, len(df))

        merged = dfs["identification"]
        for name in ["attack_description", "target_vulnerability", "impact_protection", "metadata"]:
            merged = merged.merge(dfs[name], on="id", how="inner")
            log.info("После merge с %-20s строк: %d", name, len(merged))

        return merged


if __name__ == "__main__":
    BASE_URL = "http://193.233.171.205:8000"
    LOGIN = "student"
    PASSWORD = "student_pass"

    with APIClient(BASE_URL, LOGIN, PASSWORD) as client:
        df = client.fetch_all()

    df.to_csv("sql_injections_merged.csv", index=False, encoding="utf-8")
    log.info("Сохранено: sql_injections_merged.csv, строк: %d, колонок: %d",
             len(df), df.shape[1])