// Exclusivamente datos ficticios de prueba; nunca se usan como fallback.
export const kpis = {ventas_sin_impuestos:'30.00', impuestos:'3.00', total_facturado:'33.00', cantidad_facturas:2, cantidad_pedidos:3, cantidad_clientes:2};
export const months = Array.from({length:30},(_,i)=>({anio:2013+Math.floor(i/12),mes:i%12+1,importe:'30.00',cantidad_facturas:2}));
export const products = [{producto_key:1,stock_item_id:7,stock_item_name:'Producto ficticio',ventas_sin_impuestos:'30.00'}];
export const customers = [{cliente_key:1,customer_id:9,customer_name:'Cliente ficticio',ventas_sin_impuestos:'30.00'}];

export const predictions = {
  selected_model:'moving_average_3',metric:'ventas_sin_impuestos',currency:null,completeness_verified:false,
  backtesting:{mae:'10.125',rmse:'20.5',smape:'5.125'},
  coverage:{observed_months:30,usable_months:30,observed_first:'2013-01',observed_last:'2015-06',complete_through:'2015-06',excluded_months:[],
    final_first_invoice_date:'2015-06-01',final_last_invoice_date:'2015-06-30',final_days_with_sales:20},
  uncertainty:{method:'Percentil 90 de errores sintéticos',samples_per_horizon:1},
  forecasts:['2015-07','2015-08','2015-09'].map(month=>({month,forecast:'100.00',lower:'90.00',upper:'110.00',historical_abs_error_p90:'10.00'})),
};
