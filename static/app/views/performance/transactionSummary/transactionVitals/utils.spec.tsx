import type {Point} from 'sentry/views/performance/transactionSummary/transactionVitals/types';
import {
  findNearestBucketIndex,
  getRefRect,
  mapPoint,
} from 'sentry/views/performance/transactionSummary/transactionVitals/utils';

describe('Utils', function () {
  describe('findNearestBucketIndex()', function () {
    it('returns null for insufficient data', function () {
      expect(findNearestBucketIndex([], 1)).toBeNull();
    });

    it('returns null for x axis that is too big', function () {
      const data = [
        {bin: 10, count: 0},
        {bin: 20, count: 0},
      ];

      expect(findNearestBucketIndex(data, 30)).toBeNull();
      expect(findNearestBucketIndex(data, 35)).toBeNull();
    });

    it('returns -1 for x axis that is too small', function () {
      const data = [
        {bin: 10, count: 0},
        {bin: 20, count: 0},
      ];

      expect(findNearestBucketIndex(data, 5)).toBe(-1);
      expect(findNearestBucketIndex(data, 9.9999)).toBe(-1);
    });

    it('returns the correct bin for the x axis', function () {
      const data = [
        {bin: 10, count: 0},
        {bin: 20, count: 0},
        {bin: 30, count: 0},
        {bin: 40, count: 0},
      ];

      expect(findNearestBucketIndex(data, 10)).toBe(0);
      expect(findNearestBucketIndex(data, 12)).toBe(0);
      expect(findNearestBucketIndex(data, 18.111)).toBe(0);
      expect(findNearestBucketIndex(data, 19.999)).toBe(0);
      expect(findNearestBucketIndex(data, 20)).toBe(1);
      expect(findNearestBucketIndex(data, 25)).toBe(1);
      expect(findNearestBucketIndex(data, 28.123)).toBe(1);
      expect(findNearestBucketIndex(data, 29.321)).toBe(1);
      expect(findNearestBucketIndex(data, 30)).toBe(2);
      expect(findNearestBucketIndex(data, 30.421)).toBe(2);
      expect(findNearestBucketIndex(data, 32.521)).toBe(2);
      expect(findNearestBucketIndex(data, 39.921)).toBe(2);
      expect(findNearestBucketIndex(data, 40)).toBe(3);
      expect(findNearestBucketIndex(data, 40.992)).toBe(3);
      expect(findNearestBucketIndex(data, 49.992)).toBe(3);
    });
  });

  describe('getRefRect()', function () {
    it('returns null for insufficient data', function () {
      expect(getRefRect([])).toBeNull();
      expect(getRefRect([{bin: 10, count: 0}])).toBeNull();
    });

    it('returns default rect if insufficient variation in data', function () {
      const defaultRect = {point1: {x: 0, y: 0}, point2: {x: 1, y: 1}};
      expect(
        getRefRect([
          {bin: 0, count: 0},
          {bin: 10, count: 0},
        ])
      ).toEqual(defaultRect);
      expect(
        getRefRect([
          {bin: 0, count: 1},
          {bin: 10, count: 1},
        ])
      ).toEqual(defaultRect);
    });

    it('returns two unique points in the data', function () {
      const data = [
        {bin: 10, count: 9},
        {bin: 20, count: 9},
        {bin: 30, count: 9},
        {bin: 40, count: 9},
        {bin: 50, count: 3},
      ];
      expect(getRefRect(data)).toEqual({
        point1: {x: 0, y: 3},
        point2: {x: 4, y: 9},
      });
    });
  });

  describe('mapPoint()', function () {
    it('validates src and dest rects', function () {
      const bad1 = {point1: {x: 0, y: 0}, point2: {x: 0, y: 0}};
      const bad2 = {point1: {x: 0, y: 0}, point2: {x: 0, y: 1}};
      const bad3 = {point1: {x: 0, y: 0}, point2: {x: 1, y: 0}};
      const good = {point1: {x: 0, y: 0}, point2: {x: 1, y: 1}};

      expect(mapPoint({x: 0, y: 0}, bad1, good)).toBeNull();
      expect(mapPoint({x: 0, y: 0}, bad2, good)).toBeNull();
      expect(mapPoint({x: 0, y: 0}, bad3, good)).toBeNull();
      expect(mapPoint({x: 0, y: 0}, good, bad1)).toBeNull();
      expect(mapPoint({x: 0, y: 0}, good, bad2)).toBeNull();
      expect(mapPoint({x: 0, y: 0}, good, bad3)).toBeNull();
    });

    it('maps corners correctly', function () {
      const src = {point1: {x: 0, y: 0}, point2: {x: 1, y: 1}};
      const dest = {point1: {x: 10, y: 10}, point2: {x: 20, y: 20}};

      expect(mapPoint({x: 0, y: 0}, src, dest)).toEqual({x: 10, y: 10});
      expect(mapPoint({x: 0, y: 1}, src, dest)).toEqual({x: 10, y: 20});
      expect(mapPoint({x: 1, y: 0}, src, dest)).toEqual({x: 20, y: 10});
      expect(mapPoint({x: 1, y: 1}, src, dest)).toEqual({x: 20, y: 20});
    });

    it('maps center points correctly', function () {
      const expectPointsToBeClose = (point1: Point | null, point2: Point) => {
        expect(point1?.x).toBeCloseTo(point2.x);
        expect(point1?.y).toBeCloseTo(point2?.y);
      };

      const src = {point1: {x: 0, y: 0}, point2: {x: 1, y: 1}};
      const dest = {point1: {x: 10, y: 10}, point2: {x: 20, y: 20}};

      expectPointsToBeClose(mapPoint({x: 0.5, y: 0.5}, src, dest), {x: 15, y: 15});
      expectPointsToBeClose(mapPoint({x: 0.1, y: 0.9}, src, dest), {x: 11, y: 19});
      expectPointsToBeClose(mapPoint({x: 0.875, y: 0.125}, src, dest), {
        x: 18.75,
        y: 11.25,
      });
      expectPointsToBeClose(mapPoint({x: 0.111, y: 0.999}, src, dest), {
        x: 11.11,
        y: 19.99,
      });
    });
  });
});
