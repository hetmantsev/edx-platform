import React from 'react';
import PropTypes from 'prop-types';

import { StatusAlert } from '@edx/paragon';
import SearchContainer from '../Search/SearchContainer';
import TableContainer from '../Table/TableContainer';


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
    <TableContainer
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
