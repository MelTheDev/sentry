import * as Sentry from '@sentry/react';
import {Transaction} from '@sentry/types';

import {
  isChromeTraceFormat,
  isChromeTraceObjectFormat,
  isEventedProfile,
  isJSProfile,
  isSampledProfile,
  isSchema,
  isSentrySampledProfile,
  isTypescriptChromeTraceArrayFormat,
} from '../guards/profile';

import {parseTypescriptChromeTraceArrayFormat} from './chromeTraceProfile';
import {EventedProfile} from './eventedProfile';
import {JSSelfProfile} from './jsSelfProfile';
import {Profile} from './profile';
import {SampledProfile} from './sampledProfile';
import {SentrySampledProfile} from './sentrySampledProfile';
import {
  createFrameIndex,
  createSentrySampleProfileFrameIndex,
  wrapWithSpan,
} from './utils';

export interface ImportOptions {
  transaction: Transaction | undefined;
  type: 'flamegraph' | 'flamechart';
}

export interface ProfileGroup {
  activeProfileIndex: number;
  measurements: Partial<Profiling.Schema['measurements']>;
  metadata: Partial<Profiling.Schema['metadata']>;
  name: string;
  profiles: Profile[];
  traceID: string;
  transactionID: string | null;
}

export function importProfile(
  input: Readonly<Profiling.ProfileInput>,
  traceID: string,
  type: 'flamegraph' | 'flamechart'
): ProfileGroup {
  const transaction = Sentry.startTransaction({
    op: 'import',
    name: 'profiles.import',
  });

  try {
    if (isJSProfile(input)) {
      // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
      if (transaction) {
        transaction.setTag('profile.type', 'js-self-profile');
      }
      return importJSSelfProfile(input, traceID, {transaction, type});
    }

    if (isChromeTraceFormat(input)) {
      // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
      if (transaction) {
        transaction.setTag('profile.type', 'chrometrace');
      }
      return importChromeTrace(input, traceID, {transaction, type});
    }

    if (isSentrySampledProfile(input)) {
      // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
      if (transaction) {
        transaction.setTag('profile.type', 'sentry-sampled');
      }
      return importSentrySampledProfile(input, {transaction, type});
    }

    if (isSchema(input)) {
      // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
      if (transaction) {
        transaction.setTag('profile.type', 'schema');
      }
      return importSchema(input, traceID, {transaction, type});
    }

    throw new Error('Unsupported trace format');
  } catch (error) {
    if (transaction) {
      transaction.setStatus('internal_error');
    }
    throw error;
  } finally {
    if (transaction) {
      transaction.finish();
    }
  }
}

function sortSamples(
  a: {stack: number[]; weight: number},
  b: {stack: number[]; weight: number}
) {
  const max = Math.max(a.stack.length, b.stack.length);

  for (let i = 0; i < max; i++) {
    if (a.stack[i] === undefined) {
      return -1;
    }
    if (b.stack[i] === undefined) {
      return 1;
    }
    if (a.stack[i] === b.stack[i]) {
      continue;
    }
    return a.stack[i] - b.stack[i];
  }
  return 0;
}

function sortJSSelfProfileSamples(samples: JSSelfProfiling.Trace['samples']) {
  return [...samples].sort((a, b) => {
    return a.stackId - b.stackId;
  });
}

function sortSentrySampledProfileSamples(
  samples: Profiling.SentrySampledProfile['profile']['samples']
) {
  return [...samples].sort((a, b) => {
    return a.stack_id - b.stack_id;
  });
}

function sortSchemaSamples(
  profile: Readonly<Profiling.Schema['profiles'][0]>
): {stack: number[]; weight: number}[] | null {
  if (isSampledProfile(profile)) {
    const weightsWithSamples = profile.samples.map((stack, index) => {
      return {
        stack,
        weight: profile.weights[index],
      };
    });

    return weightsWithSamples.sort(sortSamples);
  }
  if (isEventedProfile(profile)) {
    return null;
  }

  throw new TypeError('Unknown profile type');
}

// Presort samples so that they are naturally collapsed into a graph.
// it is important that we do not mutate the original input.
export function sortProfileSamples<T extends Profiling.ProfileInput>(
  input: Readonly<T>
): T {
  if (isSchema(input)) {
    const output: T = {...input, profiles: []};

    for (let i = 0; i < input.profiles.length; i++) {
      // @ts-expect-error we are assigning to a copy
      output.profiles[i] = {
        ...input.profiles[i],
        samples: [],
        weights: [],
      };

      const sorted = sortSchemaSamples(input.profiles[i]);
      if (sorted) {
        for (let j = 0; j < sorted.length; j++) {
          output.profiles[i].samples[j] = sorted[j].stack;
          output.profiles[i].weights[j] = sorted[j].weight;
        }
      }
    }

    return output;
  }
  if (isJSProfile(input)) {
    return {...input, samples: sortJSSelfProfileSamples, weights: []};
  }
  if (isChromeTraceFormat(input)) {
    throw new TypeError('Flamegraphs are not supported.');
  }
  if (isSentrySampledProfile(input)) {
    return {
      ...input,
      profile: {...input.profile, samples: sortSentrySampledProfileSamples},
    };
  }

  throw new Error('Unsupported trace format, cannot sort.');
}

function importJSSelfProfile(
  input: Readonly<JSSelfProfiling.Trace>,
  traceID: string,
  options: ImportOptions
): ProfileGroup {
  const frameIndex = createFrameIndex('web', input.frames);
  const profile = importSingleProfile(input, frameIndex, options);

  return {
    traceID,
    name: traceID,
    transactionID: null,
    activeProfileIndex: 0,
    profiles: [profile],
    measurements: {},
    metadata: {
      platform: 'javascript',
      durationNS: profile.duration,
    },
  };
}

function importChromeTrace(
  input: ChromeTrace.ProfileType,
  traceID: string,
  options: ImportOptions
): ProfileGroup {
  if (isChromeTraceObjectFormat(input)) {
    throw new Error('Chrometrace object format is not yet supported');
  }

  if (isTypescriptChromeTraceArrayFormat(input)) {
    return parseTypescriptChromeTraceArrayFormat(input, traceID, options);
  }

  throw new Error('Failed to parse trace input format');
}

function importSentrySampledProfile(
  input: Readonly<Profiling.SentrySampledProfile>,
  options: ImportOptions
): ProfileGroup {
  const frameIndex = createSentrySampleProfileFrameIndex(input.profile.frames);
  const samplesByThread: Record<
    string,
    Profiling.SentrySampledProfile['profile']['samples']
  > = {};

  for (let i = 0; i < input.profile.samples.length; i++) {
    const sample = input.profile.samples[i];
    if (!samplesByThread[sample.thread_id]) {
      samplesByThread[sample.thread_id] = [];
    }
    samplesByThread[sample.thread_id].push(sample);
  }

  for (const key in samplesByThread) {
    samplesByThread[key].sort(
      (a, b) =>
        parseInt(a.elapsed_since_start_ns, 10) - parseInt(b.elapsed_since_start_ns, 10)
    );
  }

  const profiles: Profile[] = [];

  for (const key in samplesByThread) {
    const profile: Profiling.SentrySampledProfile = {
      ...input,
      profile: {
        ...input.profile,
        samples: samplesByThread[key],
      },
    };

    profiles.push(
      wrapWithSpan(
        options.transaction,
        () => SentrySampledProfile.FromProfile(profile, frameIndex, {type: options.type}),
        {
          op: 'profile.import',
          description: 'evented',
        }
      )
    );
  }

  const firstTransaction = input.transactions?.[0];
  return {
    transactionID: firstTransaction?.id ?? null,
    traceID: firstTransaction?.trace_id ?? '',
    name: firstTransaction?.name ?? '',
    activeProfileIndex: 0,
    measurements: {},
    metadata: {
      deviceLocale: input.device.locale,
      deviceManufacturer: input.device.manufacturer,
      deviceModel: input.device.model,
      deviceOSName: input.os.name,
      deviceOSVersion: input.os.version,
      durationNS: parseInt(
        input.profile.samples[input.profile.samples.length - 1].elapsed_since_start_ns,
        10
      ),
      environment: input.environment,
      platform: input.platform,
      profileID: input.event_id,

      // these don't really work for multiple transactions
      transactionID: firstTransaction?.id,
      transactionName: firstTransaction?.name,
      traceID: firstTransaction?.trace_id,
    },
    profiles,
  };
}

function importSchema(
  input: Readonly<Profiling.Schema>,
  traceID: string,
  options: ImportOptions
): ProfileGroup {
  const frameIndex = createFrameIndex(
    input.metadata.platform === 'node' ? 'node' : 'mobile',
    input.shared.frames
  );

  return {
    traceID,
    transactionID: input.metadata.transactionID ?? null,
    name: input.metadata?.transactionName ?? traceID,
    activeProfileIndex: input.activeProfileIndex ?? 0,
    metadata: input.metadata ?? {},
    measurements: input.measurements ?? {},
    profiles: input.profiles.map(profile =>
      importSingleProfile(profile, frameIndex, options)
    ),
  };
}

function importSingleProfile(
  profile: Readonly<Profiling.ProfileInput>,
  frameIndex: ReturnType<typeof createFrameIndex>,
  {transaction, type}: ImportOptions
): Profile {
  if (isEventedProfile(profile)) {
    // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
    if (!transaction) {
      return EventedProfile.FromProfile(profile, frameIndex, {type});
    }

    return wrapWithSpan(
      transaction,
      () => EventedProfile.FromProfile(profile, frameIndex, {type}),
      {
        op: 'profile.import',
        description: 'evented',
      }
    );
  }
  if (isSampledProfile(profile)) {
    // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
    if (!transaction) {
      return SampledProfile.FromProfile(profile, frameIndex, {type});
    }

    return wrapWithSpan(
      transaction,
      () => SampledProfile.FromProfile(profile, frameIndex, {type}),
      {
        op: 'profile.import',
        description: 'sampled',
      }
    );
  }
  if (isJSProfile(profile)) {
    // In some cases, the SDK may return transaction as undefined and we dont want to throw there.
    if (!transaction) {
      return JSSelfProfile.FromProfile(profile, createFrameIndex('web', profile.frames), {
        type,
      });
    }

    return wrapWithSpan(
      transaction,
      () =>
        JSSelfProfile.FromProfile(profile, createFrameIndex('web', profile.frames), {
          type,
        }),
      {
        op: 'profile.import',
        description: 'js-self-profile',
      }
    );
  }
  throw new Error('Unrecognized trace format');
}

const tryParseInputString: JSONParser = input => {
  try {
    return [JSON.parse(input), null];
  } catch (e) {
    return [null, e];
  }
};

type JSONParser = (input: string) => [any, null] | [null, Error];

const TRACE_JSON_PARSERS: ((string) => ReturnType<JSONParser>)[] = [
  (input: string) => tryParseInputString(input),
  (input: string) => tryParseInputString(input + ']'),
];

function readFileAsString(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.addEventListener('load', (e: ProgressEvent<FileReader>) => {
      if (typeof e.target?.result === 'string') {
        resolve(e.target.result);
        return;
      }

      reject('Failed to read string contents of input file');
    });

    reader.addEventListener('error', () => {
      reject('Failed to read string contents of input file');
    });

    reader.readAsText(file);
  });
}

export async function parseDroppedProfile(
  file: File,
  parsers: JSONParser[] = TRACE_JSON_PARSERS
): Promise<Profiling.ProfileInput> {
  const fileContents = await readFileAsString(file);

  for (const parser of parsers) {
    const [json] = parser(fileContents);

    if (json) {
      if (typeof json !== 'object' || json === null) {
        throw new TypeError('Input JSON is not an object');
      }

      return json;
    }
  }

  throw new Error('Failed to parse input JSON');
}
