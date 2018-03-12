import { connect } from 'react-redux';

import EntitlementTable from './Table';

const mapStateToProps = (state) => ({
  entitlements: state.entitlements
})

// const mapDispatchToProps = (dispatch) => ({
//   fetchEntitlements: username => dispatch(fetchEntitlements(username)),
// })

const TableContainer = connect(
  mapStateToProps,
  {}
)(EntitlementTable);

export default TableContainer;