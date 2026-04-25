# Migration: Add last_lat, last_lon, speed to vehicles table.

import { MigrationInterface, QueryRunner } from 'typeorm';

export class AddPositionFields1735680000000 implements MigrationInterface {
  name = 'AddPositionFields1735680000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.startTransaction();
    try {
      // Add position fields with NOT NULL constraints and default values
      // to ensure existing rows have valid data
      await queryRunner.query(`ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "last_lat" double precision NOT NULL DEFAULT 0`);
      await queryRunner.query(`ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "last_lon" double precision NOT NULL DEFAULT 0`);
      await queryRunner.query(`ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "speed" double precision NOT NULL DEFAULT 0`);

      // Consider adding indexes if these fields will be frequently queried:
      // await queryRunner.query(`CREATE INDEX "vehicles_last_lat_idx" ON "vehicles" ("last_lat")`);
      // await queryRunner.query(`CREATE INDEX "vehicles_last_lon_idx" ON "vehicles" ("last_lon")`);
      // await queryRunner.query(`CREATE INDEX "vehicles_speed_idx" ON "vehicles" ("speed")`);

      await queryRunner.commitTransaction();
    } catch (error) {
      await queryRunner.rollbackTransaction();
      throw error;
    }
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.startTransaction();
    try {
      await queryRunner.query(`ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "speed"`);
      await queryRunner.query(`ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "last_lon"`);
      await queryRunner.query(`ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "last_lat"`);
      await queryRunner.commitTransaction();
    } catch (error) {
      await queryRunner.rollbackTransaction();
      throw error;
    }
  }
}