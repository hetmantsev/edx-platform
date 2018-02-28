import React from 'react';
import PropTypes from 'prop-types';

import { StatusAlert } from '@edx/paragon';
import SearchContainer from '../Search/SearchContainer';
import EntitlementTable from '../Table/Table';


const Main = (props) => (
  <div>
    <StatusAlert
      alertType="danger"
      dialog={ props.errorMessage }
      onClose={ props.dismissErrorMessage }
      open={ !!props.errorMessage }
    />
    <h2>
      Entitlement Support Page
    </h2>
    <SearchContainer/>
    <EntitlementTable 
      entitlements={ props.entitlements }
      openReissueModal={ props.openReissueModal }
      ecommerceUrl={ props.ecommerceUrl } 
    />
  </div>
);

Main.propTypes = {
  errorMessage: PropTypes.string.isRequired,
  dismissErrorMessage: PropTypes.func.isRequired,
};

export default Main;
