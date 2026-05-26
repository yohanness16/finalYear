# Bus Dashboard Pairing Guide

## Overview
Each physical bus dashboard tablet must be paired before drivers can log in. Pairing sets a password that drivers use daily.

## Flow
1. **Admin**: Go to Vehicles → select bus → "Generate Pairing Code"
2. **System**: Creates 5-minute code (e.g., `BUS-A7X9-K3M2`)
3. **Technician**: On the bus tablet, enter the code + a new password
4. **System**: Verifies code, stores hashed password, marks dashboard as "paired"
5. **Driver**: Each day, enters `device_id` + `password` to log in

## Re-pairing
If a tablet is replaced or the password is lost:
1. Admin: Go to Vehicles → select bus → "Unpair Device"
2. Generate a new pairing code and repeat the flow
