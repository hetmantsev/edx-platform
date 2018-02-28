import { connect } from 'react-redux';

import { fetchEntitlements } from '../../data/actions/entitlement';
import Search from './Search';

const mapStateToProps = (state) => {
  return {
    entitlements: state.entitlements
  };
}

const mapDispatchToProps = (dispatch) => ({
  fetchEntitlements: username => dispatch(fetchEntitlements(username)),
})

const SearchContainer = connect(
  mapStateToProps,
  mapDispatchToProps
)(Search);

export default SearchContainer;
