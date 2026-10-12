"""Deploy-risk model. NOTE: trained on SYNTHETIC data. Replace train() with your real pipeline."""
import os

import joblib
import numpy as np
from fastapi import FastAPI
from prometheus_client import Counter
from pydantic import BaseModel, Field
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common.observability import instrument

app = FastAPI(title="model-serving")
instrument(app, "model-serving")

MODEL_PATH = os.getenv("MODEL_PATH", "/tmp/deploy_risk.joblib")
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1-synthetic")
FEATURES = ["files_changed", "lines_changed", "test_coverage", "hour_of_day", "recent_failures"]
PREDS = Counter("predictions_total", "Predictions", ["risk"])


def train():
    rng = np.random.default_rng(42)
    n = 4000
    X = np.column_stack([
        rng.integers(1, 80, n), rng.integers(5, 3000, n), rng.uniform(20, 100, n),
        rng.integers(0, 24, n), rng.integers(0, 6, n),
    ])
    logit = (0.03 * X[:, 0] + 0.0012 * X[:, 1] - 0.04 * X[:, 2]
             + 0.8 * (X[:, 3] >= 17) + 0.5 * X[:, 4] - 2.0)
    y = rng.random(n) < 1 / (1 + np.exp(-logit))
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=1)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500))
    model.fit(Xtr, ytr)
    auc = float(roc_auc_score(yte, model.predict_proba(Xte)[:, 1]))
    joblib.dump({"model": model, "auc": auc}, MODEL_PATH)
    return model, auc


def _load():
    if os.path.exists(MODEL_PATH):
        blob = joblib.load(MODEL_PATH)
        return blob["model"], blob["auc"]
    return train()


_model, _auc = _load()


class PredictRequest(BaseModel):
    files_changed: int = Field(ge=0, le=10000)
    lines_changed: int = Field(ge=0, le=1_000_000)
    test_coverage: float = Field(ge=0, le=100)
    hour_of_day: int = Field(ge=0, le=23)
    recent_failures: int = Field(ge=0, le=100)


@app.post("/predict")
def predict(r: PredictRequest):
    x = np.array([[getattr(r, f) for f in FEATURES]])
    p = float(_model.predict_proba(x)[0, 1])
    level = "high" if p >= 0.6 else "medium" if p >= 0.3 else "low"
    PREDS.labels(level).inc()
    return {"risk_score": round(p, 4), "risk_level": level, "model_version": MODEL_VERSION}


@app.get("/model/info")
def info():
    return {"version": MODEL_VERSION, "features": FEATURES, "holdout_auc": round(_auc, 4),
            "data": "synthetic"}
