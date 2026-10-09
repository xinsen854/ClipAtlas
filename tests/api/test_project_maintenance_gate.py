import asyncio

import httpx
import pytest
from fastapi import FastAPI

from clipatlas.api.maintenance import install_maintenance_gate


@pytest.mark.asyncio
async def test_maintenance_cannot_race_active_writes_and_cache_restart_blocks_writes():
    app=FastAPI()
    install_maintenance_gate(app)
    entered,release=asyncio.Event(),asyncio.Event()

    @app.post('/work')
    async def work():
        entered.set()
        await release.wait()
        return {'ok':True}

    @app.delete('/api/v1/projects/one')
    async def delete():return {'deleted':True}

    @app.get('/read')
    async def read():return {'ok':True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        active=asyncio.create_task(client.post('/work'))
        await entered.wait()
        assert (await client.delete('/api/v1/projects/one')).status_code==409
        assert (await client.get('/read')).status_code==200
        release.set()
        assert (await active).status_code==200
        assert (await client.delete('/api/v1/projects/one')).status_code==200
        assert app.state.active_mutations==0 and not app.state.maintenance_busy
        app.state.cache_restart_required=True
        assert (await client.post('/work')).status_code==409
        assert (await client.get('/read')).status_code==200
