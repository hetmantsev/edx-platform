import { connect } from 'react-redux';

import Table from './Table';

const mapStateToProps = (state) => {
  return {
    entitlements: state.entitlements
  };
}

// const mapDispatchToProps = (dispatch) => ({
//   fetchEntitlements: username => dispatch(fetchEntitlements(username)),
// })

const SearchContainer = connect(
  mapStateToProps,
  {}
)(Search);

export default SearchContainer;