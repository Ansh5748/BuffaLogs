import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from django.db.models import Q
from django.test import TestCase
from django.utils import timezone
from impossible_travel import tasks
from impossible_travel.constants import AlertDetectionType, AlertFilterType
from impossible_travel.models import Alert, Config, Login, TaskSettings, User, UsersIP
from impossible_travel.tests.setup import Setup


def load_test_data(name):
    DATA_PATH = "impossible_travel/tests/test_data"
    with open(os.path.join(DATA_PATH, name + ".json")) as file:
        data = json.load(file)
    return data


class TestTasks(TestCase):
    @classmethod
    def setUpTestData(self):
        setup_obj = Setup()
        setup_obj.setup()

    def test_clear_models_periodically(self):
        """Testing clear_models_periodically() function"""
        user_obj = User.objects.create(username="Lorena")
        Login.objects.create(user=user_obj, timestamp=timezone.now())
        raw_data = {
            "id": 1,
            "index": "cloud",
            "ip": "1.2.3.4",
            "lat": 40.6079,
            "lon": -74.4037,
            "country": "United States",
            "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "timestamp": "2023-04-03T14:01:47.907Z",
        }
        UsersIP.objects.create(user=user_obj, ip=raw_data["ip"])
        Alert.objects.create(user=user_obj, name=AlertDetectionType.NEW_COUNTRY.value, login_raw_data=raw_data)
        self.assertTrue(User.objects.filter(username="Lorena").exists())
        self.assertTrue(Login.objects.filter(user=user_obj).exists())
        self.assertTrue(Alert.objects.filter(user=user_obj).exists())
        self.assertTrue(UsersIP.objects.filter(user=user_obj).exists())
        # Setting an old date to the updated field to check the cleaning
        old_date = timezone.now() + timedelta(days=-100)
        User.objects.filter(username="Lorena").update(updated=old_date)
        Login.objects.filter(user=user_obj).update(updated=old_date)
        Alert.objects.filter(user=user_obj).update(updated=old_date)
        UsersIP.objects.filter(user=user_obj).update(updated=old_date)
        tasks.clear_models_periodically()
        with self.assertRaises(User.DoesNotExist):
            User.objects.get(username="Lorena")
        with self.assertRaises(Login.DoesNotExist):
            Login.objects.get(user__username="Lorena")
        with self.assertRaises(Alert.DoesNotExist):
            Alert.objects.get(user__username="Lorena")
        with self.assertRaises(UsersIP.DoesNotExist):
            UsersIP.objects.get(user__username="Lorena")

    def test_update_risk_level_norisk(self):
        """Test update_risk_level() function for no_risk user"""
        # 0 alert --> no risk
        self.assertTrue(User.objects.filter(username="Lorena Goldoni").exists())
        tasks.update_risk_level()
        db_user = User.objects.get(username="Lorena Goldoni")
        self.assertEqual("No risk", db_user.risk_score)

    def test_update_risk_level_low(self):
        """Test update_risk_level() function for low risk user"""
        # 1 alert --> Low risk
        self.assertTrue(User.objects.filter(username="Lorena Goldoni").exists())
        db_user = User.objects.get(username="Lorena Goldoni")
        Alert.objects.create(user=db_user, name=AlertDetectionType.IMP_TRAVEL.value, login_raw_data="Test", description="Test_Description")
        tasks.update_risk_level()
        db_user = User.objects.get(username="Lorena Goldoni")
        self.assertEqual("Low", db_user.risk_score)

    def test_update_risk_level_medium(self):
        """Test update_risk_level() function for medium risk user"""
        #   3 alerts --> Medium risk
        self.assertTrue(User.objects.filter(username="Lorena Goldoni").exists())
        db_user = User.objects.get(username="Lorena Goldoni")
        Alert.objects.bulk_create(
            [
                Alert(user=db_user, name=AlertDetectionType.IMP_TRAVEL, login_raw_data="Test1", description="Test_Description1"),
                Alert(user=db_user, name=AlertDetectionType.NEW_DEVICE, login_raw_data="Test2", description="Test_Description2"),
                Alert(user=db_user, name=AlertDetectionType.NEW_COUNTRY, login_raw_data="Test3", description="Test_Description3"),
            ]
        )
        tasks.update_risk_level()
        db_user = User.objects.get(username="Lorena Goldoni")
        self.assertEqual("Medium", db_user.risk_score)

    def test_update_risk_level_high(self):
        """Test update_risk_level() function for high risk user"""
        #   5 alerts --> High risk
        self.assertTrue(User.objects.filter(username="Lorena Goldoni").exists())
        db_user = User.objects.get(username="Lorena Goldoni")
        Alert.objects.bulk_create(
            [
                Alert(user=db_user, name=AlertDetectionType.IMP_TRAVEL, login_raw_data="Test1", description="Test_Description1"),
                Alert(user=db_user, name=AlertDetectionType.NEW_DEVICE, login_raw_data="Test2", description="Test_Description2"),
                Alert(user=db_user, name=AlertDetectionType.NEW_COUNTRY, login_raw_data="Test3", description="Test_Description3"),
                Alert(user=db_user, name=AlertDetectionType.NEW_COUNTRY, login_raw_data="Test4", description="Test_Description4"),
                Alert(user=db_user, name=AlertDetectionType.NEW_COUNTRY, login_raw_data="Test5", description="Test_Description5"),
            ]
        )
        tasks.update_risk_level()
        db_user = User.objects.get(username="Lorena Goldoni")
        self.assertEqual("High", db_user.risk_score)

    def test_set_alert(self):
        # Add an alert and check if it is correctly inserted in the Alert Model
        db_user = User.objects.get(username="Lorena Goldoni")
        db_login = Login.objects.get(user_agent="Mozilla/5.0 (X11;U; Linux i686; en-GB; rv:1.9.1) Gecko/20090624 Ubuntu/9.04 (jaunty) Firefox/3.5")
        timestamp = db_login.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        login_data = {"timestamp": timestamp, "latitude": "45.4758", "longitude": "9.2275", "country": db_login.country, "agent": db_login.user_agent}
        name = AlertDetectionType.IMP_TRAVEL
        desc = f"{name} for User: {db_user.username}, \
                    at: {timestamp}, from: ({db_login.latitude}, {db_login.longitude})"
        alert_info = {
            "alert_name": name,
            "alert_desc": desc,
        }
        tasks.set_alert(db_user, login_data, alert_info)
        db_alert = Alert.objects.get(user=db_user, name=AlertDetectionType.IMP_TRAVEL)
        self.assertIsNotNone(db_alert)
        self.assertEqual("Imp Travel", db_alert.name)
        self.assertTrue(db_alert.is_filtered)
        self.assertListEqual([AlertFilterType.ALLOWED_COUNTRY_FILTER], db_alert.filter_type)

    def test_set_alert_vip_user(self):
        app_config = Config.objects.get(id=1)
        app_config.alert_is_vip_only = True
        app_config.save()
        # Test for alert in case of a vip_user
        db_user = User.objects.get(username="Lorena Goldoni")
        db_login = Login.objects.filter(user=db_user).first()
        timestamp = db_login.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        login_data = {"timestamp": timestamp, "latitude": "45.4758", "longitude": "9.2275", "country": db_login.country, "agent": db_login.user_agent}
        name = AlertDetectionType.IMP_TRAVEL
        desc = f"{name} for User: {db_user.username}, \
                    at: {timestamp}, from: ({db_login.latitude}, {db_login.longitude})"
        alert_info = {
            "alert_name": name,
            "alert_desc": desc,
        }
        tasks.set_alert(db_user, login_data, alert_info)
        db_alert = Alert.objects.get(user=db_user, name=AlertDetectionType.IMP_TRAVEL)
        self.assertTrue(db_alert.is_filtered)
        self.assertEqual([AlertFilterType.IS_VIP_FILTER, AlertFilterType.ALLOWED_COUNTRY_FILTER], db_alert.filter_type)

    def test_process_logs_data_lost(self):
        TaskSettings.objects.create(
            task_name="process_logs", start_date=timezone.datetime(2023, 4, 18, 10, 0), end_date=timezone.datetime(2023, 4, 18, 10, 30, 0)
        )
        tasks.process_logs()
        new_end_date_expected = timezone.now() - timedelta(minutes=1)
        new_start_date_expected = new_end_date_expected - timedelta(minutes=30)
        process_task = TaskSettings.objects.get(task_name="process_logs")
        self.assertLessEqual((process_task.start_date - new_start_date_expected).total_seconds(), 5)
        self.assertLessEqual((process_task.end_date - new_end_date_expected).total_seconds(), 5)

    def test_process_logs_loop(self):
        start = timezone.now() - timedelta(hours=5) - timedelta(minutes=1)
        end = timezone.now() - timedelta(hours=4.5) - timedelta(minutes=1)
        TaskSettings.objects.create(task_name="process_logs", start_date=start, end_date=end)
        # Let entire exec for loop
        tasks.process_logs()
        start_date_expected = start + timedelta(hours=3)
        end_date_expected = end + timedelta(hours=3)
        process_task = TaskSettings.objects.get(task_name="process_logs")
        self.assertLessEqual((start_date_expected - process_task.start_date).total_seconds(), 5)
        self.assertLessEqual((end_date_expected - process_task.end_date).total_seconds(), 5)
        # Now not entire for loop executed
        tasks.process_logs()
        start_date_expected = start + timedelta(hours=5)
        end_date_expected = end + timedelta(hours=4.5)

    def test_check_fields_logins(self):
        fields1 = load_test_data("test_check_fields_part1")
        fields2 = load_test_data("test_check_fields_part2")
        db_user = User.objects.get(username="Aisha Delgado")
        # First part - Expected logins in Login Model:
        #   1. at 2023-05-03T06:50:03.768Z from India,
        #   2. at 2023-05-03T06:57:27.768Z from Japan,
        #   3. at 2023-05-03T07:10:23.154Z from United States
        tasks.check_fields(db_user, fields1)
        self.assertEqual(3, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3").count())
        self.assertEqual(1, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="India").count())
        self.assertEqual(6, Login.objects.get(user=db_user, country="India").timestamp.hour)
        self.assertEqual(50, Login.objects.get(user=db_user, country="India").timestamp.minute)
        self.assertEqual(3, Login.objects.get(user=db_user, country="India").timestamp.second)
        self.assertEqual(1, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="United States").count())
        self.assertEqual(7, Login.objects.get(user=db_user, country="United States").timestamp.hour)
        self.assertEqual(10, Login.objects.get(user=db_user, country="United States").timestamp.minute)
        self.assertEqual(23, Login.objects.get(user=db_user, country="United States").timestamp.second)
        self.assertEqual(1, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="Japan").count())
        self.assertEqual(6, Login.objects.get(user=db_user, country="Japan").timestamp.hour)
        self.assertEqual(57, Login.objects.get(user=db_user, country="Japan").timestamp.minute)
        self.assertEqual(27, Login.objects.get(user=db_user, country="Japan").timestamp.second)
        # Second part - Expected changed logins in Login Model:
        #   4. at 2023-05-03T07:14:22.768Z from India with user_agent: Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0
        #   5. at 2023-05-03T07:18:38.768Z from India with user_agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)
        #   6. at 2023-05-03T07:20:36.154Z from United States with user_agent: Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0
        tasks.check_fields(db_user, fields2)
        self.assertEqual(6, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3").count())
        self.assertEqual(3, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="India").count())
        self.assertEqual(
            7, Login.objects.get(user=db_user, country="India", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0").timestamp.hour
        )
        self.assertEqual(
            14,
            Login.objects.get(user=db_user, country="India", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0").timestamp.minute,
        )
        self.assertEqual(
            22,
            Login.objects.get(user=db_user, country="India", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0").timestamp.second,
        )
        self.assertEqual(
            7,
            Login.objects.get(
                user=db_user, country="India", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
            ).timestamp.hour,
        )
        self.assertEqual(
            18,
            Login.objects.get(
                user=db_user, country="India", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
            ).timestamp.minute,
        )
        self.assertEqual(
            38,
            Login.objects.get(
                user=db_user, country="India", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
            ).timestamp.second,
        )
        self.assertEqual(2, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="United States").count())
        self.assertEqual(
            7,
            Login.objects.get(
                user=db_user, country="United States", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0"
            ).timestamp.hour,
        )
        self.assertEqual(
            31,
            Login.objects.get(
                user=db_user, country="United States", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0"
            ).timestamp.minute,
        )
        self.assertEqual(
            36,
            Login.objects.get(
                user=db_user, country="United States", user_agent="Mozilla/5.0 (Android 4.4; Mobile; rv:41.0) Gecko/41.0 Firefox/41.0"
            ).timestamp.second,
        )
        self.assertEqual(2, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="United States").count())
        self.assertEqual(7, Login.objects.filter(user=db_user, country="United States").last().timestamp.hour)
        self.assertEqual(31, Login.objects.filter(user=db_user, country="United States").last().timestamp.minute)
        self.assertEqual(36, Login.objects.filter(user=db_user, country="United States").last().timestamp.second)
        self.assertEqual(1, Login.objects.filter(user=db_user, index="cloud-test_data-2023-5-3", country="Japan").count())
        self.assertEqual(6, Login.objects.get(user=db_user, country="Japan").timestamp.hour)
        self.assertEqual(57, Login.objects.get(user=db_user, country="Japan").timestamp.minute)
        self.assertEqual(27, Login.objects.get(user=db_user, country="Japan").timestamp.second)

    def test_check_fields_alerts(self):
        fields1 = load_test_data("test_check_fields_part1")
        fields2 = load_test_data("test_check_fields_part2")
        db_user = User.objects.get(username="Aisha Delgado")
        tasks.check_fields(db_user, fields1)
        # First part - Expected alerts in Alert Model:
        #   1. at 2023-05-03T06:55:31.768Z alert NEW DEVICE
        #   2. at 2023-05-03T06:55:31.768Z alert NEW COUNTRY
        #   3. at 2023-05-03T06:55:31.768Z alert IMP TRAVEL
        #   4. at 2023-05-03T06:57:27.768Z alert NEW DEVICE
        #   4. at 2023-05-03T06:57:27.768Z alert NEW COUNTRY
        #   5. at 2023-05-03T06:57:27.768Z alert IMP TRAVEL
        #   6. at 2023-05-03T07:10:23.154Z alert IMP TRAVEL
        self.assertEqual(7, Alert.objects.filter(user=db_user).count())
        self.assertEqual(0, Alert.objects.filter(is_filtered=True).count())
        self.assertEqual(0, Alert.objects.filter(~Q(filter_type=[])).count())
        self.assertEqual(7, Alert.objects.filter(is_filtered=False).count())
        self.assertEqual(7, Alert.objects.filter(filter_type=[]).count())
        new_device_alerts_fields1 = Alert.objects.filter(user=db_user, name=AlertDetectionType.NEW_DEVICE)
        self.assertEqual(2, new_device_alerts_fields1.count())
        new_country_alerts_fields1 = Alert.objects.filter(user=db_user, name=AlertDetectionType.NEW_COUNTRY)
        self.assertEqual(2, new_country_alerts_fields1.count())
        imp_travel_alerts_fields1 = Alert.objects.filter(user=db_user, name=AlertDetectionType.IMP_TRAVEL)
        self.assertEqual(3, imp_travel_alerts_fields1.count())
        # check new_device alerts for fields1 logins
        self.assertEqual("New Device", new_device_alerts_fields1[0].name)
        self.assertEqual("Login from new device for User: Aisha Delgado, at: 2023-05-03T06:55:31.768Z", new_device_alerts_fields1[0].description)
        self.assertEqual("New Device", new_device_alerts_fields1[1].name)
        self.assertEqual("Login from new device for User: Aisha Delgado, at: 2023-05-03T06:57:27.768Z", new_device_alerts_fields1[1].description)
        # check new_country alerts for fields1 logins
        self.assertEqual("New Country", new_country_alerts_fields1[0].name)
        self.assertEqual(
            "Login from new country for User: Aisha Delgado, at: 2023-05-03T06:55:31.768Z, from: United States", new_country_alerts_fields1[0].description
        )
        self.assertEqual("New Country", new_country_alerts_fields1[1].name)
        self.assertEqual("Login from new country for User: Aisha Delgado, at: 2023-05-03T06:57:27.768Z, from: Japan", new_country_alerts_fields1[1].description)
        # check imp_travel alerts for fields1 logins
        self.assertEqual("Imp Travel", imp_travel_alerts_fields1[0].name)
        self.assertEqual(
            "Impossible Travel detected for User: Aisha Delgado, at: 2023-05-03T06:55:31.768Z, from: United States, previous country: India, distance covered at 133973 Km/h",
            imp_travel_alerts_fields1[0].description,
        )
        self.assertEqual("Imp Travel", imp_travel_alerts_fields1[1].name)
        self.assertEqual(
            "Impossible Travel detected for User: Aisha Delgado, at: 2023-05-03T06:57:27.768Z, from: Japan, previous country: United States, distance covered at 344009 Km/h",
            imp_travel_alerts_fields1[1].description,
        )
        self.assertEqual("Imp Travel", imp_travel_alerts_fields1[2].name)
        self.assertEqual(
            "Impossible Travel detected for User: Aisha Delgado, at: 2023-05-03T07:10:23.154Z, from: United States, previous country: Japan, distance covered at 52564 Km/h",
            imp_travel_alerts_fields1[2].description,
        )
        self.assertEqual(0, Alert.objects.filter(user=db_user, filter_type=["is_vip_filter"]).count())

        # Adding "Aisha Delgado" to vip users
        Config.objects.filter(id=1).delete()
        config = Config.objects.create(allowed_countries=["Italy", "Romania"], vip_users=["Aisha Delgado"], alert_is_vip_only=True)
        config.save()

        # Second part - Expected new alerts in Alert Model:
        #   7. at 2023-05-03T07:14:22.768Z alert NEW DEVICE
        #   8. at 2023-05-03T07:14:22.768Z alert IMP TRAVEL
        #   9. at 2023-05-03T07:18:38.768Z alert NEW DEVICE
        #   10. at 2023-05-03T07:18:38.768Z alert IMP TRAVEL
        #   11. at 2023-05-03T07:20:36.154Z alert IMP TRAVEL

        # get IDs of old alerts to check the new alerts
        new_device_alerts_fields1_ids = list(new_device_alerts_fields1.values_list("id", flat=True))

        tasks.check_fields(db_user, fields2)
        self.assertEqual(12, Alert.objects.filter(user=db_user).count())
        # get new_device alerts relating to fields2 making query all_new_device_alerts - new_device_alerts_fields1
        all_new_device_alerts = Alert.objects.filter(user=db_user, name=AlertDetectionType.NEW_DEVICE)
        self.assertEqual(4, all_new_device_alerts.count())
        new_device_alerts_fields2 = all_new_device_alerts.exclude(id__in=new_device_alerts_fields1_ids)
        self.assertEqual(2, new_device_alerts_fields2.count())
        # check new_device alerts for fields2
        self.assertEqual("New Device", new_device_alerts_fields2[0].name)
        self.assertEqual("Login from new device for User: Aisha Delgado, at: 2023-05-03T07:14:22.768Z", new_device_alerts_fields2[0].description)
        self.assertEqual("New Device", new_device_alerts_fields2[1].name)
        self.assertEqual("Login from new device for User: Aisha Delgado, at: 2023-05-03T07:18:38.768Z", new_device_alerts_fields2[1].description)

        # same old new_country alert relating to fields1 logins
        self.assertEqual(2, Alert.objects.filter(user=db_user, name=AlertDetectionType.NEW_COUNTRY).count())

        self.assertEqual(6, Alert.objects.filter(user=db_user, name=AlertDetectionType.IMP_TRAVEL).count())

    def test_check_fields_usersip(self):
        db_user = User.objects.get(username="Aisha Delgado")
        fields1 = load_test_data("test_check_fields_part1")
        fields2 = load_test_data("test_check_fields_part2")
        fields3 = load_test_data("test_check_fields_part3")
        tasks.check_fields(db_user, fields1)
        # First part: Check presence of ips in the UsersIP model
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.37").exists())
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.17").exists())
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.20").exists())
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.11").exists())
        self.assertEqual(4, UsersIP.objects.filter(user=db_user).count())
        # Second part: Check presence of ips in the UsersIP model
        tasks.check_fields(db_user, fields2)
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.40").exists())
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.35").exists())
        self.assertTrue(UsersIP.objects.filter(user=db_user, ip="203.0.113.15").exists())
        self.assertEqual(7, UsersIP.objects.filter(user=db_user).count())
        # Check No duplicated ips
        self.assertEqual(1, UsersIP.objects.filter(user=db_user, ip="203.0.113.17").count())
        self.assertEqual(1, UsersIP.objects.filter(user=db_user, ip="203.0.113.11").count())
        # Third part: no new alerts because all the ips have already been used
        tasks.check_fields(db_user, fields3)
        self.assertEqual(0, Alert.objects.filter(user=db_user, login_raw_data__timestamp__gt=datetime(2023, 5, 4, 0, 0, 0).isoformat()).count())

    # TO DO
    # @patch("impossible_travel.tasks.check_fields")
    # @patch.object(tasks.Search, "execute")
    # def test_process_user(self, mock_execute, mock_check_fields):
    #     data_elastic_sorted_dot_not = []
    #     imp_travel = impossible_travel.Impossible_Travel()
    #     data_elastic = load_test_data("test_data_process_user")
    #     data_elastic_sorted = sorted(data_elastic, key=lambda d: d["@timestamp"])
    #     for data in data_elastic_sorted:
    #         data_elastic_sorted_dot_not.append(DictStruct(kwargs=data))
    #     data_results = load_test_data("test_data_process_user_result")
    #     mock_execute.return_value = data_elastic_sorted_dot_not
    #     start_date = timezone.datetime(2023, 3, 8, 0, 0, 0)
    #     end_date = timezone.datetime(2023, 3, 8, 23, 59, 59)
    #     iso_start_date = imp_travel.validate_timestamp(start_date)
    #     iso_end_date = imp_travel.validate_timestamp(end_date)
    #     db_user = User.objects.get(username="Lorena Goldoni")
    #     tasks.process_user(db_user, iso_start_date, iso_end_date)
    #     mock_check_fields.assert_called_once_with(db_user, data_results)
