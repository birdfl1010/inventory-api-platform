import polars as pl


def execute_query(conn, query: str, schema: dict | None = None) -> pl.DataFrame:
    """Execute a Snowflake query and return the result as a Polars DataFrame."""
    with conn.cursor() as cursor:
        cursor.execute(query)
        result = cursor.fetchall()
        columns = schema if schema else [desc[0] for desc in cursor.description]
    return pl.DataFrame(result, schema=columns, orient="row")


def execute_query_in_batches(
    conn,
    query: str,
    schema: dict | None = None,
    batch_size: int = 5000,
):
    """Stream Snowflake query results as Polars DataFrames in batches."""
    with conn.cursor() as cursor:
        cursor.execute(query)
        columns = schema if schema else [desc[0] for desc in cursor.description]

        while True:
            result = cursor.fetchmany(batch_size)
            if not result:
                break
            yield pl.DataFrame(result, schema=columns, orient="row")
