"""Sesión de carga: miles de operaciones contra una base local, buscando bugs.

No son los tests de `tests/`. Aquellos son unitarios puros y corren en el CI en
cinco segundos; esto **necesita una base de verdad**, tarda minutos y se lanza a
mano cuando se quiere sacudir el sistema:

    cd backend
    .\\.venv\\Scripts\\python.exe -m tests.carga.sesion --corridas 1000

Por eso vive en un paquete aparte y sin archivos `test_*.py`: pytest no lo
levanta solo. Un `pytest` que quisiera abrir Postgres rompería el CI y la
costumbre de correr la suite antes de cada commit.

Ver §Registro de bugs y §Sesión de carga.
"""
