import logging
from datetime import datetime

logger = logging.getLogger(__name__)

MIN_SESSIONS = 5


class PredictionService:
    def __init__(self):
        self._electricity_model = None
        self._water_model = None
        self._electricity_trained = False
        self._water_trained = False

    def train(self, sessions: list) -> dict:
        elec = [s for s in sessions if s.type == "electricity" and s.status == "completed"
                and s.started_at and s.ended_at and s.energy_kwh is not None]
        water = [s for s in sessions if s.type == "water" and s.status == "completed"
                 and s.started_at and s.ended_at and s.water_liters is not None]

        result = {"electricity_trained": False, "water_trained": False}

        if len(elec) >= MIN_SESSIONS:
            try:
                import numpy as np
                from sklearn.linear_model import LinearRegression
                X = np.array([[(s.ended_at - s.started_at).total_seconds() / 60] for s in elec])
                y = np.array([s.energy_kwh for s in elec])
                model = LinearRegression()
                model.fit(X, y)
                self._electricity_model = model
                self._electricity_trained = True
                result["electricity_trained"] = True
                logger.info(f"Electricity model trained on {len(elec)} sessions")
            except Exception as e:
                logger.error(f"Failed to train electricity model: {e}")

        if len(water) >= MIN_SESSIONS:
            try:
                import numpy as np
                from sklearn.linear_model import LinearRegression
                X = np.array([[(s.ended_at - s.started_at).total_seconds() / 60] for s in water])
                y = np.array([s.water_liters for s in water])
                model = LinearRegression()
                model.fit(X, y)
                self._water_model = model
                self._water_trained = True
                result["water_trained"] = True
                logger.info(f"Water model trained on {len(water)} sessions")
            except Exception as e:
                logger.error(f"Failed to train water model: {e}")

        return result

    def predict_electricity(self, duration_minutes: float) -> dict | None:
        if not self._electricity_trained or self._electricity_model is None:
            return None
        import numpy as np
        X = np.array([[duration_minutes]])
        predicted = float(self._electricity_model.predict(X)[0])
        return {
            "predicted_duration_minutes": duration_minutes,
            "predicted_consumption": max(0.0, predicted),
            "unit": "kWh",
            "type": "electricity",
        }

    def predict_water(self, duration_minutes: float) -> dict | None:
        if not self._water_trained or self._water_model is None:
            return None
        import numpy as np
        X = np.array([[duration_minutes]])
        predicted = float(self._water_model.predict(X)[0])
        return {
            "predicted_duration_minutes": duration_minutes,
            "predicted_consumption": max(0.0, predicted),
            "unit": "liters",
            "type": "water",
        }

    @property
    def electricity_ready(self) -> bool:
        return self._electricity_trained

    @property
    def water_ready(self) -> bool:
        return self._water_trained


prediction_service = PredictionService()
