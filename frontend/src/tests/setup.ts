import * as auth from '../lib/supabase';
import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
beforeEach(()=>{vi.spyOn(auth,'getAccessToken').mockResolvedValue('synthetic-test-token');});

afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();});
