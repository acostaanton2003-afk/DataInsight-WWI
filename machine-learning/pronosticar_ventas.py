"""Ejecutar desde la raíz: python machine-learning/pronosticar_ventas.py."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wwi_forecast.data import ForecastError,read_months
from wwi_forecast.artifacts import experiment,publish


def main():
    parser=argparse.ArgumentParser(description='Experimento local de ventas mensuales; SELECT únicamente.')
    parser.add_argument('--expected-months',type=int,default=41)
    parser.add_argument('--complete-through',help='Último mes declarado completo: YYYY-MM. Sin declarar se excluye el último observado.')
    parser.add_argument('--coverage-note',default='',help='Evidencia de cierre, sin secretos.')
    parser.add_argument('--output-root',help='Subdirectorio local dentro de artifacts/.')
    args=parser.parse_args()
    try:
        if args.expected_months<1:raise ForecastError('Cantidad de meses inválida.')
        summary,model,frame,records=experiment(read_months(),args.expected_months,args.complete_through,args.coverage_note)
        destination=publish(summary,model,frame,records,args.output_root)
    except ForecastError as error:
        print('Experimento detenido:',str(error));return 1
    except Exception:
        print('Experimento detenido por error de cálculo o publicación; no se muestran detalles privados.');return 1
    print('Meses observados/utilizables:',summary['coverage']['observed_months'],summary['coverage']['usable_months'])
    print('Modelo seleccionado:',summary['evaluation']['selected_model'])
    for name,result in summary['evaluation']['results'].items():
        print(name,'selección:',result['selection'],'prueba final:',result['holdout'])
    for warning in summary['evaluation']['warnings']:print('ADVERTENCIA:',warning)
    for row in summary['forecasts']:print(row)
    print('Artefactos locales:',destination)
    return 0


if __name__=='__main__':raise SystemExit(main())
