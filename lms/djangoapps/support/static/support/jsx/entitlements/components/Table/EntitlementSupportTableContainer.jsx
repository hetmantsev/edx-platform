import { connect } from 'react-redux';

import EntitlementSupportTable from './EntitlementSupportTable';

const mapStateToProps = state => ({
  entitlements: state.entitlements,
});

const EntitlementSupportTableContainer = connect(
  mapStateToProps,
)(EntitlementSupportTable);

export default EntitlementSupportTableContainer;
