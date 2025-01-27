/* eslint-env node */

import type {Configuration, RuleSetRule} from '@rspack/core';
import rspack from '@rspack/core';
import childProcess from 'node:child_process';
import path from 'node:path';

import baseConfig from '../rspack.config';

const commitHash =
  process.env.SENTRY_BUILD ||
  childProcess.execSync('git rev-parse HEAD', {encoding: 'utf8'}).trim();

const findLoader = (loaderName: string) =>
  baseConfig.module?.rules?.find(
    (rule: any) =>
      rule &&
      typeof rule === 'object' &&
      (rule.loader === loaderName || rule.use?.loader === loaderName)
  ) as RuleSetRule;

export default {
  mode: baseConfig.mode,
  context: baseConfig.context,
  resolve: baseConfig.resolve,

  target: 'node',
  entry: {
    config: 'sentry/chartcuterie/config',
  },

  module: {
    rules: [findLoader('builtin:swc-loader'), findLoader('po-catalog-loader')],
  },

  plugins: [
    new rspack.DefinePlugin({
      'process.env.COMMIT_SHA': JSON.stringify(commitHash),
    }),
  ],

  output: {
    path: path.join(__dirname, 'chartcuterie'),
    libraryTarget: 'commonjs2',
  },

  optimization: {minimize: false},
} as Configuration;
