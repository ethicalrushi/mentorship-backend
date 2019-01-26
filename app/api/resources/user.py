from datetime import datetime

from flask import request
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity
from flask_restplus import Resource, marshal, Namespace

from app.api.validations.user import *
from app.api.email_utils import send_email_verification_message
from app.api.models.user import *
from app.api.dao.user import UserDAO
from app.api.resources.common import auth_header_parser
from app.utils.responses import ResponseMessages

users_ns = Namespace('Users', description='Operations related to users')
add_models_to_namespace(users_ns)

DAO = UserDAO()  # User data access object


@users_ns.route('users')
class UserList(Resource):

    @classmethod
    @jwt_required
    @users_ns.doc('list_users')
    @users_ns.marshal_list_with(public_user_api_model)
    @users_ns.expect(auth_header_parser)
    def get(cls):
        """
        Returns list of all the users.
        """
        user_id = get_jwt_identity()
        return DAO.list_users(user_id)


@users_ns.route('users/<int:user_id>')
@users_ns.param('user_id', 'The user identifier')
class OtherUser(Resource):

    @classmethod
    @jwt_required
    @users_ns.doc('get_user')
    @users_ns.expect(auth_header_parser)
    @users_ns.response(201, ResponseMessages.SUCCESS, public_user_api_model)
    @users_ns.response(400, ResponseMessages.USER_ID_IS_NOT_VALID)
    @users_ns.response(404, ResponseMessages.USER_DOES_NOT_EXIST)
    def get(cls, user_id):
        """
        Returns a user.
        """
        # Validate arguments
        if not OtherUser.validate_param(user_id):
            return {"message": ResponseMessages.USER_ID_IS_NOT_VALID}, 400

        requested_user = DAO.get_user(user_id)
        if requested_user is None:
            return {"message": ResponseMessages.USER_DOES_NOT_EXIST}, 404
        else:
            return marshal(requested_user, public_user_api_model), 201

    @staticmethod
    def validate_param(user_id):
        return isinstance(user_id, int)


@users_ns.route('user')
@users_ns.response(404, ResponseMessages.USER_NOT_FOUND[0])
class MyUserProfile(Resource):

    @classmethod
    @jwt_required
    @users_ns.doc('get_user')
    @users_ns.expect(auth_header_parser, validate=True)
    @users_ns.marshal_with(full_user_api_model)  # , skip_none=True
    def get(cls):
        """
        Returns a user.
        """
        user_id = get_jwt_identity()
        return DAO.get_user(user_id)

    @classmethod
    @jwt_required
    @users_ns.doc('update_user_profile')
    @users_ns.expect(auth_header_parser, update_user_request_body_model)
    @users_ns.response(200, ResponseMessages.USER_SUCCESSFULLY_UPDATED)
    @users_ns.response(404, ResponseMessages.USER_NOT_FOUND[0])
    def put(cls):
        """
        Updates user profile
        """

        data = request.json

        is_valid = validate_update_profile_request_data(data)

        if is_valid != {}:
            return is_valid, 400

        user_id = get_jwt_identity()
        return DAO.update_user_profile(user_id, data)

    @classmethod
    @jwt_required
    @users_ns.doc('delete_user')
    @users_ns.expect(auth_header_parser, validate=True)
    @users_ns.response(200, ResponseMessages.USER_SUCCESSFULLY_DELETED[1])
    @users_ns.response(404, ResponseMessages.USER_NOT_FOUND[0])
    def delete(cls):
        """
        Deletes user.
        """
        user_id = get_jwt_identity()
        return DAO.delete_user(user_id)


@users_ns.route('user/change_password')
class ChangeUserPassword(Resource):

    @classmethod
    @jwt_required
    @users_ns.doc('update_user_password')
    @users_ns.expect(auth_header_parser, change_password_request_data_model, validate=True)
    def put(cls):
        """
        Updates the user's password
        """
        user_id = get_jwt_identity()
        data = request.json
        is_valid = validate_new_password(data)
        if is_valid != {}:
            return is_valid, 400
        return DAO.change_password(user_id, data)


@users_ns.route('users/verified')
class VerifiedUser(Resource):

    @classmethod
    @jwt_required
    @users_ns.doc('get_verified_users')
    @users_ns.marshal_list_with(public_user_api_model)  # , skip_none=True
    @users_ns.expect(auth_header_parser)
    def get(cls):
        """
        Returns all verified users.
        """
        user_id = get_jwt_identity()
        return DAO.list_users(user_id, is_verified=True)


@users_ns.route('register')
class UserRegister(Resource):

    @classmethod
    @users_ns.doc('create_user')
    @users_ns.response(201, ResponseMessages.USER_SUCCESSFULLY_CREATED)
    @users_ns.expect(register_user_api_model, validate=True)
    def post(cls):
        """
        Creates a new user.
        """

        data = request.json

        is_valid = validate_user_registration_request_data(data)

        if is_valid != {}:
            return is_valid, 400

        result = DAO.create_user(data)

        if result[1] is 200:
            send_email_verification_message(data['name'], data['email'])

        return result


@users_ns.route('user/confirm_email/<string:token>')
@users_ns.param('token', 'Token sent to the user\'s email')
class UserEmailConfirmation(Resource):

    @classmethod
    def get(cls, token):
        """Confirms the user's account."""

        return DAO.confirm_registration(token)


@users_ns.route('user/resend_email')
class UserResendEmailConfirmation(Resource):

    @classmethod
    @users_ns.expect(resend_email_request_body_model)
    def post(cls):
        """Sends the user a new verification email."""

        data = request.json

        is_valid = validate_resend_email_request_data(data)

        if is_valid != {}:
            return is_valid, 400

        user = DAO.get_user_by_email(data['email'])
        if user is None:
            return {"message": ResponseMessages.USER_IS_NOT_REGISTERED_IN_THE_SYSTEM}, 404

        if user.is_email_verified:
            return {"message": ResponseMessages.EMAIL_ALREADY_CONFIRMED}, 403

        send_email_verification_message(user.name, data['email'])

        return {"message": ResponseMessages.EMAIL_VERIFICATION_MESSAGE}, 200


@users_ns.route('login')
class LoginUser(Resource):

    @classmethod
    @users_ns.doc('login')
    @users_ns.response(200, ResponseMessages.LOGIN_SUCCESSFUL , login_response_body_model)
    @users_ns.expect(login_request_body_model)
    def post(cls):
        """
        Login user

        The user can login with (username or email) + password.
        Username field can be either the User's username or the email.
        The return value is an access token and the expiry timestamp.
        The token is valid for 1 week.
        """
        # if not request.is_json:
        #     return {'msg': 'Missing JSON in request'}, 400

        username = request.json.get('username', None)
        password = request.json.get('password', None)

        if not username:
            return {'message': ResponseMessages.USERNAME_FIELD_IS_MISSING}, 400
        if not password:
            return {'message': ResponseMessages.PASSWORD_FIELD_IS_MISSING[1]}, 400

        user = DAO.authenticate(username, password)

        if not user:
            return {'message': ResponseMessages.USERNAME_OR_PASSWORD_FIELD_IS_INCORRECTLY_FILLED_UP}, 404

        if not user.is_email_verified:
            return {'message': ResponseMessages.USER_HAS_NOT_VERIFIED_EMAIL_BEFORE_LOGIN}, 403

        access_token = create_access_token(identity=user.id)

        from run import application
        expiry = datetime.utcnow() + application.config.get('JWT_ACCESS_TOKEN_EXPIRES')

        return {
            'access_token': access_token,
            'expiry': expiry.timestamp()
        }, 200


@users_ns.route('home')
@users_ns.expect(auth_header_parser, validate=True)
@users_ns.response(200, ResponseMessages.SUCCESFUL_RESPONSE, home_response_body_model)
@users_ns.response(404, ResponseMessages.USER_NOT_FOUND[1])
class UserHomeStatistics(Resource):
    @classmethod
    @jwt_required
    @users_ns.expect(auth_header_parser)
    def get(cls):
        """Get Statistics regarding the current user

        Returns:
            A dict containing user stats
        """
        user_id = get_jwt_identity()
        stats = DAO.get_user_statistics(user_id)
        if not stats:
            return {'message': ResponseMessages.USER_NOT_FOUND[1]}, 404

        return stats, 200
