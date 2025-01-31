import styled from '@emotion/styled';

import {LinkButton} from 'sentry/components/button';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import type {Event} from 'sentry/types/event';
import type {Group} from 'sentry/types/group';
import type {Organization} from 'sentry/types/organization';
import type {Project} from 'sentry/types/project';
import {getConfigForIssueType} from 'sentry/utils/issueTypeConfig';
import useOrganization from 'sentry/utils/useOrganization';
import {SidebarSectionTitle} from 'sentry/views/issueDetails/streamline/sidebar/sidebar';

interface DetectorDetails {
  description?: string;
  detectorPath?: string;
}

export function getDetectorDetails({
  event,
  organization,
  project,
}: {
  event: Event;
  organization: Organization;
  project: Project;
}): DetectorDetails {
  /**
   * Rather than check the issue category, we just check all the current set locations
   * for Alert Rule IDs. Hopefully we can consolidate this when we move to the detector system.
   * Ideally, this function wouldn't even check the event, but rather the group/issue.
   */
  const metricAlertRuleId = event?.contexts?.metric_alert?.alert_rule_id;
  if (metricAlertRuleId) {
    return {
      detectorPath: `/organizations/${organization.slug}/alerts/rules/details/${metricAlertRuleId}/`,
      // TODO(issues): We can probably enrich this description with details from the alert itself.
      description: t(
        'This issue was created by a metric alert detector. View the detector details to learn more.'
      ),
    };
  }

  const cronSlug = event?.tags?.find(({key}) => key === 'monitor.slug')?.value;
  if (cronSlug) {
    return {
      detectorPath: `/organizations/${organization.slug}/alerts/rules/crons/${project.slug}/${cronSlug}/details/`,
      description: t(
        'This issue was created by a cron monitor. View the monitor details to learn more.'
      ),
    };
  }

  const uptimeAlertRuleId = event?.tags?.find(tag => tag?.key === 'uptime_rule')?.value;
  if (uptimeAlertRuleId) {
    return {
      detectorPath: `/organizations/${organization.slug}/alerts/rules/uptime/${project.slug}/${uptimeAlertRuleId}/details/`,
      // TODO(issues): Update this to mention detectors when that language is user-facing
      description: t(
        'This issue was created by an uptime alert rule. After 2 consecutive failed check-ins, an open period will be created.'
      ),
    };
  }
  return {
    detectorPath: undefined,
    description: undefined,
  };
}

export function DetectorSection({
  event,
  group,
  project,
}: {
  event: Event;
  group: Group;
  project: Project;
}) {
  const organization = useOrganization();
  const {detectorPath, description} = getDetectorDetails({event, organization, project});
  const issueConfig = getConfigForIssueType(group, project);

  if (!detectorPath) {
    return null;
  }

  return (
    <div>
      <SidebarSectionTitle>
        {issueConfig.detector.title ?? t('Detector')}
      </SidebarSectionTitle>
      {description && <DetectorDescription>{description}</DetectorDescription>}
      <LinkButton
        aria-label={issueConfig.detector.ctaText ?? t('View detector details')}
        href={detectorPath}
        style={{width: '100%'}}
        size="sm"
      >
        {issueConfig.detector.ctaText ?? t('View detector details')}
      </LinkButton>
    </div>
  );
}

const DetectorDescription = styled('p')`
  margin: ${space(1)} 0;
`;
