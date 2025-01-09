import styled from '@emotion/styled';
import {motion} from 'framer-motion';

import testableTransition from 'sentry/utils/testableTransition';

const GenericFooter = styled(motion.div)`
  width: 100%;
  position: fixed;
  bottom: 0;
  left: 0;
  height: 72px;
  z-index: 100;
  display: flex;
  background-color: ${p => p.theme.background};
  justify-content: space-between;
  box-shadow: ${p => p.theme.dropShadowHeavyTop};
`;

GenericFooter.defaultProps = {
  initial: 'initial',
  animate: 'animate',
  exit: 'exit',
  variants: {animate: {}},
  transition: testableTransition({
    staggerChildren: 0.2,
  }),
};

export default GenericFooter;
