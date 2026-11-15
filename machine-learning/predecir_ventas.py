"""Repetir predicción desde parámetros JSON locales, sin red ni reentrenar."""
import argparse
import json
from wwi_forecast.artifacts import load_model
from wwi_forecast.data import ForecastError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',required=True)
    args=parser.parse_args()
    try:rows=load_model(args.run_dir)
    except (ForecastError,ValueError,TypeError,KeyError):
        print('No se pudo predecir con el modelo local; revise ruta y formato.');return 1
    print(json.dumps(rows,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
