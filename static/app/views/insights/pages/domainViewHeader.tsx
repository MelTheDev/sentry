import {Fragment} from 'react';

import {Breadcrumbs, type Crumb} from 'sentry/components/breadcrumbs';
import ButtonBar from 'sentry/components/buttonBar';
import FeedbackWidgetButton from 'sentry/components/feedback/widget/feedbackWidgetButton';
import * as Layout from 'sentry/components/layouts/thirds';
import {TabList, Tabs} from 'sentry/components/tabs';
import {t} from 'sentry/locale';
import {useNavigate} from 'sentry/utils/useNavigate';
import useOrganization from 'sentry/utils/useOrganization';
import {useModuleTitles} from 'sentry/views/insights/common/utils/useModuleTitle';
import {
  type RoutableModuleNames,
  useModuleURLBuilder,
} from 'sentry/views/insights/common/utils/useModuleURL';
import type {ModuleName} from 'sentry/views/insights/types';

export type Props = {
  domainBaseUrl: string;
  domainOverviewPageTitle: string;
  domainTitle: string;
  headerTitle: React.ReactNode;
  modules: ModuleName[];
  selectedModule: ModuleName | undefined;
  additionalBreadCrumbs?: Crumb[];
  additonalHeaderActions?: React.ReactNode;
  hideDefaultTabs?: boolean;
  tabs?: {onTabChange: (key: string) => void; tabList: React.ReactNode; value: string};
};

type Tab = {
  key: string;
  label: string;
};

export function DomainViewHeader({
  modules,
  headerTitle,
  domainTitle,
  domainOverviewPageTitle,
  selectedModule,
  hideDefaultTabs,
  additonalHeaderActions,
  additionalBreadCrumbs = [],
  domainBaseUrl,
  tabs,
}: Props) {
  const navigate = useNavigate();
  const organization = useOrganization();
  const moduleURLBuilder = useModuleURLBuilder();
  const moduleTitles = useModuleTitles();

  const baseCrumbs: Crumb[] = [
    {
      label: t('Performance'),
      to: undefined, // There is no base /performance/ page
      preservePageFilters: true,
    },
    {
      label: domainTitle,
      to: domainBaseUrl,
      preservePageFilters: true,
    },
    {
      label: selectedModule ? moduleTitles[selectedModule] : domainOverviewPageTitle,
      to: selectedModule
        ? `${moduleURLBuilder(selectedModule as RoutableModuleNames)}/`
        : domainBaseUrl,
      preservePageFilters: true,
    },
    ...additionalBreadCrumbs,
  ];

  const showModuleTabs = organization.features.includes('insights-entry-points');

  const defaultHandleTabChange = (key: ModuleName | typeof domainOverviewPageTitle) => {
    if (key === selectedModule || (key === domainOverviewPageTitle && !module)) {
      return;
    }
    if (!key) {
      return;
    }
    if (key === domainOverviewPageTitle) {
      navigate(domainBaseUrl);
      return;
    }
    navigate(`${moduleURLBuilder(key as RoutableModuleNames)}/`);
  };

  const tabValue =
    hideDefaultTabs && tabs?.value
      ? tabs.value
      : selectedModule ?? domainOverviewPageTitle;

  const handleTabChange =
    hideDefaultTabs && tabs ? tabs.onTabChange : defaultHandleTabChange;

  const tabList: Tab[] = [
    {
      key: domainOverviewPageTitle,
      label: domainOverviewPageTitle,
    },
  ];

  if (showModuleTabs) {
    tabList.push(
      ...modules.map(moduleName => ({
        key: moduleName,
        label: moduleTitles[moduleName],
      }))
    );
  }

  return (
    <Fragment>
      <Layout.Header>
        <Layout.HeaderContent>
          <Breadcrumbs crumbs={baseCrumbs} />

          <Layout.Title>{headerTitle}</Layout.Title>
        </Layout.HeaderContent>
        <Layout.HeaderActions>
          <ButtonBar gap={1}>
            {additonalHeaderActions}
            <FeedbackWidgetButton />
          </ButtonBar>
        </Layout.HeaderActions>
        <Tabs value={tabValue} onChange={handleTabChange}>
          {!hideDefaultTabs && (
            <TabList hideBorder>
              {tabList.map(tab => (
                <TabList.Item key={tab.key}>{tab.label}</TabList.Item>
              ))}
            </TabList>
          )}
          {hideDefaultTabs && tabs && tabs.tabList}
        </Tabs>
      </Layout.Header>
    </Fragment>
  );
}
