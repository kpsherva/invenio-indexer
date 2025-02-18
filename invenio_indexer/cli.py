# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2016-2022 CERN.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""CLI for indexer."""

import click
from celery.messaging import establish_connection
from flask import current_app
from flask.cli import with_appcontext
from invenio_pidstore.models import PersistentIdentifier, PIDStatus
from invenio_search.cli import index

from .api import RecordIndexer
from .tasks import process_bulk_queue


def abort_if_false(ctx, param, value):
    """Abort command is value is False."""
    if not value:
        ctx.abort()


def resultcallback(group):
    """Compatibility layer for Click 7 and 8."""
    if hasattr(group, "result_callback") and group.result_callback is not None:
        decorator = group.result_callback()
    else:
        # Click < 8.0
        decorator = group.resultcallback()
    return decorator


@index.command()
@click.option("--delayed", "-d", is_flag=True, help="Run indexing in background.")
@click.option(
    "--concurrency",
    "-c",
    default=1,
    type=int,
    help="Number of concurrent indexing tasks to start.",
)
@click.option(
    "--queue",
    "-q",
    type=str,
    help="Name of the celery queue used to put the tasks into.",
)
@click.option("--version-type", help="The search engine version type to use.")
@click.option(
    "--raise-on-error/--skip-errors",
    default=True,
    help="Controls if the search engine bulk indexing errors raise an exception.",
)
@with_appcontext
def run(delayed, concurrency, version_type=None, queue=None, raise_on_error=True):
    """Run bulk record indexing."""
    if delayed:
        celery_kwargs = {
            "kwargs": {
                "version_type": version_type,
                "search_bulk_kwargs": {"raise_on_error": raise_on_error},
            }
        }
        click.secho(
            "Starting {0} tasks for indexing records...".format(concurrency), fg="green"
        )
        if queue is not None:
            celery_kwargs.update({"queue": queue})
        for c in range(0, concurrency):
            process_bulk_queue.apply_async(**celery_kwargs)
    else:
        click.secho("Indexing records...", fg="green")
        RecordIndexer(version_type=version_type).process_bulk_queue(
            search_bulk_kwargs={"raise_on_error": raise_on_error}
        )


@index.command()
@click.option(
    "--yes-i-know",
    is_flag=True,
    callback=abort_if_false,
    expose_value=False,
    prompt="Do you really want to reindex all records?",
)
@click.option("-t", "--pid-type", multiple=True, required=True)
@with_appcontext
def reindex(pid_type):
    """Reindex all records.

    :param pid_type: Pid type.
    """
    click.secho("Sending records to indexing queue ...", fg="green")

    query = (
        x[0]
        for x in PersistentIdentifier.query.filter_by(
            object_type="rec", status=PIDStatus.REGISTERED
        )
        .filter(PersistentIdentifier.pid_type.in_(pid_type))
        .values(PersistentIdentifier.object_uuid)
    )
    RecordIndexer().bulk_index(query)
    click.secho('Execute "run" command to process the queue!', fg="yellow")


@index.group(chain=True)
def queue():
    """Manage indexing queue."""


@resultcallback(queue)
@with_appcontext
def process_actions(actions):
    """Process queue actions."""
    queue = current_app.config["INDEXER_MQ_QUEUE"]
    with establish_connection() as c:
        q = queue(c)
        for action in actions:
            q = action(q)


@queue.command("init")
def init_queue():
    """Initialize indexing queue."""

    def action(queue):
        queue.declare()
        click.secho("Indexing queue has been initialized.", fg="green")
        return queue

    return action


@queue.command("purge")
def purge_queue():
    """Purge indexing queue."""

    def action(queue):
        queue.purge()
        click.secho("Indexing queue has been purged.", fg="green")
        return queue

    return action


@queue.command("delete")
def delete_queue():
    """Delete indexing queue."""

    def action(queue):
        queue.delete()
        click.secho("Indexing queue has been deleted.", fg="green")
        return queue

    return action
