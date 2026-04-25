/**
 * Tests for Routes and Stops CRUD and route-aware telemetry validation.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import request from 'supertest';
import app from '@/app';
import { getDb } from '@/db';
import { RouteService, StopService } from '@/services';

describe('Routes & Stops API', () => {
  beforeEach(async () => {
    const db = await getDb();
    await db.query('TRUNCATE routes, stops, route_stops RESTART IDENTITY CASCADE');
  });

  it('should create a route with stops', async () => {
    const routeRes = await request(app)
      .post('/api/v1/routes')
      .send({
        routeNumber: '121',
        name: 'Kality ↔ Meskel',
        origin: 'Kality',
        destination: 'Meskel',
      });
    expect(routeRes.status).toBe(201);
    const routeId = routeRes.body.id;

    const stopRes = await request(app)
      .post('/api/v1/stops')
      .send({
        name: 'Kality Bus Station',
        lat: 9.0167,
        lon: 38.7667,
        routeId,
        sequenceOrder: 1,
        isTerminal: true,
      });
    expect(stopRes.status).toBe(201);
    expect(stopRes.body.routeId).toBe(routeId);
  });

  it('should GET route stops', async () => {
    const routeRes = await request(app)
      .post('/api/v1/routes')
      .send({ routeNumber: '150', name: 'Gulele ↔ Saris', origin: 'Gulele', destination: 'Saris' });
    const routeId = routeRes.body.id;

    await request(app).post('/api/v1/stops').send({
      name: 'Gulele Square', lat: 9.038, lon: 38.745, routeId, sequenceOrder: 1, isTerminal: true,
    });
    await request(app).post('/api/v1/stops').send({
      name: 'Saris Market', lat: 9.048, lon: 38.76, routeId, sequenceOrder: 2, isTerminal: true,
    });

    const stopsRes = await request(app).get(`/api/v1/routes/${routeId}/stops`);
    expect(stopsRes.status).toBe(200);
    expect(stopsRes.body.length).toBe(2);
  });

  it('should validate GPS is on route', async () => {
    // Create route with stops forming a rough corridor
    const routeRes = await request(app)
      .post('/api/v1/routes')
      .send({ routeNumber: '122', name: 'Akaki ↔ Entoto', origin: 'Akaki', destination: 'Entoto' });
    const routeId = routeRes.body.id;

    await request(app).post('/api/v1/stops').send({
      name: 'Akaki Terminal', lat: 9.000, lon: 38.750, routeId, sequenceOrder: 1, isTerminal: true,
    });
    await request(app).post('/api/v1/stops').send({
      name: 'Entoto Summit', lat: 9.050, lon: 38.785, routeId, sequenceOrder: 2, isTerminal: true,
    });

    // Simulate telemetry close to stops => should pass
    const onRouteRes = await request(app)
      .post('/api/v1/telemetry')
      .send({ deviceId: 'IMEI_TEST_ROUTE', lat: 9.025, lon: 38.767, pixelCount: 4000 });
    expect(onRouteRes.status).toBe(200);
    expect(onRouteRes.body.routeChecked).toBe(true);

    // Far off route => should be rejected
    const offRouteRes = await request(app)
      .post('/api/v1/telemetry')
      .send({ deviceId: 'IMEI_TEST_ROUTE2', lat: 10.0, lon: 40.0, pixelCount: 4000 });
    expect(offRouteRes.status).toBe(200);
    expect(offRouteRes.body.reason).toBe('off_route');
  });
});