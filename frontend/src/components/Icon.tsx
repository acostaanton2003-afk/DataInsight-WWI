export function Icon({name, size=20}: {name:string; size?:number}) {
  const paths: Record<string,string> = {
    grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    trend:'M3 17l6-6 4 4 8-10 M15 5h6v6',
    box:'M12 3l9 5-9 5-9-5 9-5z M3 8v9l9 5 9-5V8 M12 13v9 M7 5l9 5',
    people:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
    refresh:'M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12-1l2 6 M4 12l2 6a7 7 0 0 0 12-1',
    document:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z M14 2v6h6 M8 13h8 M8 17h5',
    calendar:'M4 5h16v16H4z M16 3v4 M8 3v4 M4 11h16',
    arrow:'M7 17L17 7 M7 7h10v10',
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.trend}/></svg>;
}
