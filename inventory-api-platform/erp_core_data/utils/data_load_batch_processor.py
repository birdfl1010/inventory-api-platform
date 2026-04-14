# erp_core/utils.py
from itertools import islice


def batch_load(data_generator, model_class, batch_size=999):
    """Batch loads data into the given model."""
    while True:
        batch = list(islice(data_generator, batch_size))
        if not batch:
            break
        model_class.objects.bulk_create(batch, batch_size=batch_size)
